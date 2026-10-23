// Client regressions for PROTOCOL.md (replica reducer, durable adapter, e2e).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createReplica, reduce, selectView} from '../client/replica.mjs';
import {load, save, sendOnce, sendBatchOnce} from '../client/durable.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const EPOCH = 'e-1';
const BIG = '9007199254740993';
const body = (extra = {}) => ({title: 'Pump', assignee: null, visits: 0, done: false, ...extra});
const rec = (id, revision, seq, extra = {}, deleted = false) =>
  ({id, revision, seq, body: body(extra), deleted});
const snap = (rows, cut, extra = {}) => ({type: 'SNAPSHOT', page: {kind: 'snapshot',
  tenant: 'north', epoch: EPOCH, cut, rows, confirmed: [], next_cursor: null, ...extra}});
const pull = (from, after, events, confirmed, until = after) => ({type: 'PULL', page: {
  kind: 'events', tenant: 'north', epoch: EPOCH, from, after, until, events, confirmed,
  next_cursor: null}});
const ack = (mutation, record, device = 'van-7') =>
  ({type: 'ACK', response: {ok: true, tenant: 'north', device, mutation, record}});
const conf = (mutation, id, seq, device = 'van-7') => ({device, mutation, id, seq});
const run = (state, ...actions) => actions.reduce(reduce, state);
const fresh = () => createReplica('north', 'van-7');
const deepFreeze = value => {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
};
const visible = state => Object.fromEntries(selectView(state).records.map(r => [r.id, r.body]));

test('incident trace produces the expected view', () => {
  const input = readFileSync(join(ROOT, 'incidents/client-actions.json'), 'utf8');
  const result = spawnSync(process.execPath, [join(ROOT, 'client/trace.mjs')], {input});
  assert.equal(result.status, 0, String(result.stderr));
  const {state, view} = JSON.parse(result.stdout);
  const expected = JSON.parse(input);
  assert.deepEqual(state.pending.map(p => p.mutation), expected.expected_pending);
  assert.equal(state.checkpoint, expected.expected_checkpoint);
  assert.equal(view.records[0].body.visits, expected.expected_visible.visits);
  assert.equal(view.records[0].body.assignee, expected.expected_visible.assignee);
  const bad = spawnSync(process.execPath, [join(ROOT, 'client/trace.mjs')],
    {input: JSON.stringify({actions: [{type: 'ACK'}]})});
  assert.notEqual(bad.status, 0);
  assert.match(String(bad.stderr), /ACK/);
});

test('reducer is pure and decimal comparisons keep precision', () => {
  const start = deepFreeze(run(fresh(), snap([rec('pump', BIG, BIG)], BIG)));
  const action = deepFreeze({type: 'PUSH', epoch: EPOCH,
    record: rec('pump', '9007199254740994', '9007199254740994', {visits: 1})});
  const next = reduce(start, action);
  assert.equal(next.base.pump.revision, '9007199254740994');
  assert.equal(start.base.pump.revision, BIG);
  const stale = reduce(next, {type: 'PUSH', epoch: EPOCH,
    record: rec('pump', '9007199254740992', '9007199254740992', {visits: 7})});
  assert.equal(stale.base.pump.body.visits, 1);
  assert.throws(() => reduce(next, {type: 'PUSH', epoch: EPOCH,
    record: rec('pump', '9007199254740994', '9007199254740994', {visits: 2})}), /equal revision/);
  assert.equal(next.checkpoint, BIG, 'push never advances checkpoint');
  assert.doesNotThrow(() => JSON.stringify(next));
});

test('ACK removes only its mutation and never rolls back newer state', () => {
  let s = run(fresh(), snap([rec('pump', '43', '100', {visits: 9})], '100'),
    {type: 'QUEUE', mutation: 'm-9', id: 'pump', kind: 'visit', data: {amount: 1}},
    {type: 'SEND'},
    {type: 'QUEUE', mutation: 'm-10', id: 'pump', kind: 'patch', data: {assignee: 'Mira'}},
    {type: 'QUEUE', mutation: 'm-11', id: 'other', kind: 'create', data: body()});
  const wire = s.pending[0].wire;
  s = reduce(s, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '45', '102', {visits: 10,
    assignee: 'Lee'})});
  assert.deepEqual(reduce(s, {type: 'SEND'}).pending[0].wire, wire, 'repeated SEND is stable');
  s = reduce(s, ack('m-9', rec('pump', '44', '101', {visits: 10})));
  assert.deepEqual(s.pending.map(p => p.mutation), ['m-10', 'm-11']);
  assert.equal(s.base.pump.revision, '45');
  assert.equal(visible(s).pump.visits, 10);
  assert.equal(visible(s).pump.assignee, 'Mira');
  const again = reduce(s, ack('m-9', rec('pump', '44', '101', {visits: 10})));
  assert.deepEqual(again.pending, s.pending);
  assert.throws(() => reduce(s, ack('m-10', rec('pump', '46', '103'), 'van-8')), /Foreign/);
});

test('conflict blocks, resolve retries with a fresh base or drops', () => {
  let s = run(fresh(), snap([rec('pump', '3', '3')], '3'),
    {type: 'QUEUE', mutation: 'a', id: 'pump', kind: 'patch', data: {done: true}},
    {type: 'QUEUE', mutation: 'b', id: 'pump', kind: 'visit', data: {amount: 1}},
    {type: 'SEND'});
  s = reduce(s, {type: 'CONFLICT', mutation: 'a', current: rec('pump', '4', '4', {title: 'X'})});
  assert.equal(s.pending[0].blocked, true);
  assert.equal(s.pending[0].wire.base, '3');
  assert.deepEqual(selectView(s).conflicts, ['a']);
  assert.equal(reduce(s, {type: 'SEND'}).pending[0].wire.base, '3', 'blocked is not sent');
  assert.throws(() => reduce(s, {type: 'RESOLVE', mutation: 'b', mode: 'drop'}));
  assert.throws(() => reduce(s, {type: 'RESOLVE', mutation: 'a', mode: 'retry',
    newMutation: 'b'}), /unique/);
  const retried = run(s, {type: 'RESOLVE', mutation: 'a', mode: 'retry', newMutation: 'a2'},
    {type: 'SEND'});
  assert.equal(retried.pending[0].mutation, 'a2');
  assert.equal(retried.pending[0].wire.base, '4');
  const dropped = reduce(s, {type: 'RESOLVE', mutation: 'a', mode: 'drop'});
  assert.deepEqual(dropped.pending.map(p => p.mutation), ['b']);
});

test('pending edits cannot revive deleted entities; restore can', () => {
  const s = run(fresh(), snap([rec('pump', '2', '2', {}, true), rec('ok', '1', '1')], '2'),
    {type: 'QUEUE', mutation: 'p', id: 'pump', kind: 'patch', data: {done: true}},
    {type: 'QUEUE', mutation: 'q', id: 'ghost', kind: 'visit', data: {amount: 1}},
    {type: 'QUEUE', mutation: 'r', id: 'pump', kind: 'restore', data: {assignee: 'Jo'}},
    {type: 'QUEUE', mutation: 's', id: 'pump', kind: 'visit', data: {amount: 2}});
  const view = selectView(s);
  assert.deepEqual(view.conflicts, ['p', 'q']);
  assert.deepEqual(view.records.map(r => [r.id, r.body.visits, r.body.assignee]),
    [['ok', 0, null], ['pump', 2, 'Jo']]);
});

test('snapshot staging is atomic, frozen and replays post-cut deliveries', () => {
  let s = run(fresh(), snap([rec('old', '1', '1'), rec('pump', '1', '2')], '2'));
  const page1 = {kind: 'snapshot', tenant: 'north', epoch: EPOCH, cut: '10',
    rows: [rec('a', '1', '5')], confirmed: [], next_cursor: 'c1'};
  s = run(s, {type: 'SNAPSHOT', page: page1}, {type: 'SNAPSHOT', page: page1});
  assert.deepEqual(Object.keys(s.base).sort(), ['old', 'pump'], 'partial page not applied');
  assert.equal(s.checkpoint, '2');
  assert.throws(() => reduce(s, {type: 'PULL', page: pull('2', '3', [], [])}));
  assert.throws(() => reduce(s, {type: 'SNAPSHOT', page: {...page1, cut: '11'}}), /Mixed/);
  assert.throws(() => reduce(s, {type: 'SNAPSHOT', page: {...page1,
    rows: [rec('a', '2', '6')]}}), /Mixed/);
  s = reduce(s, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '3', '12', {done: true})});
  s = reduce(s, {type: 'PUSH', epoch: EPOCH, record: rec('b', '1', '7')});
  s = reduce(s, {type: 'SNAPSHOT', page: {...page1, rows: [rec('pump', '2', '9')],
    next_cursor: null}});
  assert.deepEqual(Object.keys(s.base).sort(), ['a', 'pump']);
  assert.equal(s.base.pump.revision, '3');
  assert.equal(s.checkpoint, '10');
  assert.equal(s.snapshot, null);
  assert.throws(() => reduce(s, snap([], '9')), /Backward/);
  assert.throws(() => reduce(fresh(), {type: 'PUSH', epoch: EPOCH, record: rec('a', '1', '1')}));
});

test('pull pages are contiguous, idempotent and never jump the checkpoint', () => {
  let s = run(fresh(), snap([], BIG));
  const next = '9007199254740995';
  s = reduce(s, pull(BIG, next, [rec('a', '1', next)], [conf('x', 'a', next, 'van-9')]));
  assert.equal(s.checkpoint, next);
  assert.deepEqual(reduce(s, pull(BIG, next, [rec('a', '1', next)], [])), s);
  assert.throws(() => reduce(s, pull('9007199254740996', '9007199254740999', [], [])),
    /Noncontiguous/);
  assert.throws(() => reduce(s, pull(next, '9007199254740999', [rec('b', '1', next)], [])),
    /outside/);
  const legacy = pull(next, '9007199254740999', [], undefined);
  delete legacy.page.confirmed;
  assert.equal(reduce(s, legacy).checkpoint, '9007199254740999');
});

test('pull confirmations retire sent intents only', () => {
  let s = run(fresh(), snap([rec('pump', '1', '1')], '1'),
    {type: 'QUEUE', mutation: 'm-1', id: 'pump', kind: 'visit', data: {amount: 1}},
    {type: 'SEND'},
    {type: 'QUEUE', mutation: 'm-2', id: 'pump', kind: 'patch', data: {done: true}});
  const event = rec('pump', '3', '3', {visits: 1, assignee: 'Lee'});
  const page = pull('1', '3', [rec('pump', '2', '2', {visits: 1}), event],
    [conf('m-1', 'pump', '2'), conf('m-2', 'pump', '3', 'van-8')]);
  const done = reduce(s, page);
  assert.deepEqual(done.pending.map(p => p.mutation), ['m-2']);
  assert.equal(visible(done).pump.visits, 1, 'visit not doubled');
  assert.equal(reduce(done, ack('m-1', rec('pump', '2', '2', {visits: 1}))).base.pump.revision,
    '3', 'delayed ACK is safe');
  assert.deepEqual(reduce(done, page), done, 'consumed page does not act again');
  assert.throws(() => reduce(s, pull('1', '2', [rec('pump', '2', '2')],
    [conf('m-2', 'pump', '2')])), /unsent/);
  assert.throws(() => reduce(s, pull('1', '2', [rec('other', '1', '2')],
    [conf('m-1', 'other', '2')])), /different entity/);
});

test('snapshot confirmations retire superseded own writes at completion', () => {
  let s = run(fresh(), snap([rec('pump', '1', '1')], '1'),
    {type: 'QUEUE', mutation: 'm-1', id: 'pump', kind: 'visit', data: {amount: 1}},
    {type: 'SEND'},
    {type: 'QUEUE', mutation: 'm-2', id: 'pump', kind: 'patch', data: {done: true}});
  const first = {kind: 'snapshot', tenant: 'north', epoch: EPOCH, cut: '5',
    rows: [rec('pump', '3', '4', {visits: 1, assignee: 'Lee'})],
    confirmed: [conf('m-1', 'pump', '2')], next_cursor: 'more'};
  s = reduce(s, {type: 'SNAPSHOT', page: first});
  assert.equal(s.pending.length, 2, 'confirmations wait for completion');
  s = reduce(s, {type: 'SNAPSHOT', page: {...first, rows: [], confirmed: [],
    next_cursor: null}});
  assert.deepEqual(s.pending.map(p => p.mutation), ['m-2']);
  assert.deepEqual(visible(s).pump, {...body({visits: 1, assignee: 'Lee', done: true})});
});

test('batch send freezes bases and survives partial confirmation', () => {
  let s = run(fresh(), snap([rec('pump', '7', '7'), rec('valve', '3', '7')], '7'),
    {type: 'QUEUE', mutation: 'v', id: 'pump', kind: 'visit', data: {amount: 1}},
    {type: 'QUEUE', mutation: 'd', id: 'pump', kind: 'patch', data: {done: true}},
    {type: 'QUEUE', mutation: 'x', id: 'valve', kind: 'patch', data: {done: true}},
    {type: 'QUEUE', mutation: 'n', id: 'new', kind: 'create', data: body()},
    {type: 'QUEUE', mutation: 'later', id: 'valve', kind: 'patch', data: {assignee: 'Jo'}},
    {type: 'SEND_BATCH', batch: 'b1', count: 4});
  const wire = s.batch.wire;
  assert.deepEqual(wire.operations.map(o => o.base), ['7', '8', '3', '0']);
  assert.equal(s.pending[1].wire.base, '8');
  assert.throws(() => reduce(s, {type: 'SEND'}), /batch/);
  assert.throws(() => reduce(s, {type: 'SEND_BATCH', batch: 'b2', count: 4}));
  assert.throws(() => reduce(s, {type: 'CONFLICT', mutation: 'v', current: null}));
  s = reduce(s, pull('7', '8', [rec('pump', '8', '8', {visits: 1})], [conf('v', 'pump', '8')]));
  assert.deepEqual(s.pending.map(p => p.mutation), ['d', 'x', 'n', 'later']);
  assert.deepEqual(reduce(s, {type: 'SEND_BATCH', batch: 'b1', count: 4}).batch.wire, wire);
  const receipts = [['v', rec('pump', '8', '8', {visits: 1})],
    ['d', rec('pump', '9', '9', {visits: 1, done: true})],
    ['x', rec('valve', '4', '10', {done: true})], ['n', rec('new', '1', '11')]];
  const response = {ok: true, tenant: 'north', device: 'van-7', batch: 'b1',
    responses: receipts.map(([mutation, record]) =>
      ({ok: true, tenant: 'north', device: 'van-7', mutation, record}))};
  assert.throws(() => reduce(s, {type: 'ACK_BATCH', response: {...response,
    responses: response.responses.slice(0, 3)}}));
  assert.throws(() => reduce(s, {type: 'ACK_BATCH', response: {...response,
    responses: [...response.responses].reverse()}}));
  s = reduce(s, {type: 'ACK_BATCH', response});
  assert.deepEqual(s.pending.map(p => p.mutation), ['later']);
  assert.equal(s.batch, null);
  assert.equal(visible(s).valve.assignee, 'Jo');
  assert.deepEqual(reduce(s, {type: 'ACK_BATCH', response}), s);
  assert.throws(() => reduce(s, {type: 'ACK_BATCH', response: {...response, batch: 'b9'}}));
});

test('recovery boundary preserves outbox and requires a new snapshot', () => {
  let s = run(fresh(), snap([rec('pump', '1', '1')], '1'),
    {type: 'QUEUE', mutation: 'v', id: 'pump', kind: 'visit', data: {amount: 1}},
    {type: 'QUEUE', mutation: 'q', id: 'pump', kind: 'patch', data: {done: true}},
    {type: 'QUEUE', mutation: 'z', id: 'pump', kind: 'patch', data: {assignee: 'Z'}},
    {type: 'SEND_BATCH', batch: 'b', count: 2});
  const wire = s.batch.wire;
  s = reduce(s, {type: 'SNAPSHOT', page: {kind: 'snapshot', tenant: 'north', epoch: EPOCH,
    cut: '4', rows: [], confirmed: [], next_cursor: 'x'}});
  assert.throws(() => reduce(s, {type: 'RECOVERY_REQUIRED', epoch: 'other', floor: '9'}));
  s = run(s, {type: 'RECOVERY_REQUIRED', epoch: EPOCH, floor: '9'},
    {type: 'RECOVERY_REQUIRED', epoch: EPOCH, floor: '6'});
  assert.equal(s.needsSnapshot, true);
  assert.equal(s.recoveryFloor, '9');
  assert.equal(s.snapshot, null);
  assert.equal(s.checkpoint, '1');
  assert.deepEqual(s.batch.wire, wire);
  assert.equal(s.pending.length, 3);
  for (const action of [{type: 'SEND'}, {type: 'SEND_BATCH', batch: 'b', count: 2},
    pull('1', '2', [], [])]) assert.throws(() => reduce(s, action));
  s = reduce(s, {type: 'QUEUE', mutation: 'w', id: 'pump', kind: 'visit', data: {amount: 1}});
  assert.throws(() => reduce(s, snap([], '8')));
  s = reduce(s, snap([rec('pump', '3', '3', {visits: 1, done: true})], '12',
    {confirmed: [conf('v', 'pump', '2'), conf('q', 'pump', '3')]}));
  assert.equal(s.needsSnapshot, false);
  assert.deepEqual(s.pending.map(p => p.mutation), ['z', 'w']);
  assert.deepEqual(reduce(s, {type: 'SEND_BATCH', batch: 'b', count: 2}).batch.wire, wire);
});

test('durable save is atomic and missing state is an error', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'replica-'));
  try {
    const path = join(dir, 'state.json');
    await assert.rejects(load(path));
    await save(path, fresh());
    const changed = reduce(fresh(), {type: 'QUEUE', mutation: 'a', id: 'x', kind: 'create',
      data: body()});
    await assert.rejects(save(path, changed, stage => {
      if (stage === 'before_rename') throw new Error('crash');
    }), /crash/);
    assert.deepEqual(await load(path), fresh());
    assert.deepEqual(readdirSync(dir), ['state.json']);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});

// ---- end-to-end against the real Python service ---------------------------

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer().listen(0, '127.0.0.1', () => {
      const {port} = server.address();
      server.close(() => resolve(port));
    }).on('error', reject);
  });
}

async function startServer(db) {
  const port = await freePort();
  const child = spawn('python3', ['-m', 'server.http', '--db', db, '--port', String(port)],
    {cwd: ROOT, stdio: 'ignore'});
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 200; i += 1) {
    try {
      if ((await fetch(`${base}/health`)).ok) break;
    } catch {
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  }
  const call = async (path, payload) => {
    const response = await fetch(base + path, payload === undefined ? {} : {
      method: 'POST', body: JSON.stringify(payload)});
    const json = await response.json();
    if (!response.ok) throw Object.assign(new Error(json.code), {status: response.status, json});
    return json;
  };
  return {child, call};
}

async function catchUp(call, path) {
  let state = await load(path);
  let cursor = null;
  const checkpoint = state.checkpoint;
  do {
    const query = new URLSearchParams({tenant: 'north', limit: '1', checkpoint,
      ...(cursor ? {cursor} : {})});
    const page = await call(`/pull?${query}`);
    state = reduce(state, {type: 'PULL', page});
    cursor = page.next_cursor;
  } while (cursor);
  await save(path, state);
  return state;
}

async function bootstrap(call, path) {
  let state = await load(path);
  let cursor = null;
  do {
    const query = new URLSearchParams({tenant: 'north', limit: '1', ...(cursor ? {cursor} : {})});
    const page = await call(`/snapshot?${query}`);
    state = reduce(state, {type: 'SNAPSHOT', page});
    cursor = page.next_cursor;
  } while (cursor);
  await save(path, state);
  return state;
}

test('end-to-end: lost responses, retries, compaction and recovery', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'e2e-'));
  const db = join(dir, 'site.sqlite');
  const seq = spawnSync('python3', ['-c', `
import sqlite3, sys
sys.path.insert(0, '.')
from server.store import Store
Store(sys.argv[1])
with sqlite3.connect(sys.argv[1]) as db:
    db.execute("INSERT INTO sqlite_sequence(name,seq) VALUES ('events', 9007199254740993)")
`, db], {cwd: ROOT});
  assert.equal(seq.status, 0, String(seq.stderr));
  const {child, call} = await startServer(db);
  try {
    const path = join(dir, 'van7.json');
    const lost = async wire => {
      await call(wire.operations ? '/batch' : '/mutate', wire);
      throw new Error('response lost');
    };
    await call('/mutate', {tenant: 'north', device: 'desk', mutation: 'c', id: 'pump',
      base: '0', kind: 'create', data: body({title: 'Ünïcode pump 🚰'})});
    await save(path, fresh());
    let state = await bootstrap(call, path);
    const epoch = state.epoch;
    for (const [mutation, kind, data] of [['v1', 'visit', {amount: 1}],
      ['p1', 'patch', {assignee: 'Mira'}]]) {
      state = reduce(state, {type: 'QUEUE', mutation, id: 'pump', kind, data});
    }
    await save(path, state);
    await assert.rejects(sendOnce(path, lost), /lost/);
    const persisted = (await load(path)).pending[0].wire;
    assert.equal(persisted.base, '1');
    state = await sendOnce(path, wire => {
      assert.deepEqual(wire, persisted);
      return call('/mutate', wire);
    });
    assert.deepEqual(state.pending.map(p => p.mutation), ['p1']);
    state = await sendOnce(path, wire => call('/mutate', wire));
    assert.equal(state.pending.length, 0);
    assert.equal(state.base.pump.body.visits, 1);

    // Lost batch response, partial pull catch-up, then compaction.
    for (const [mutation, kind, data] of [['v2', 'visit', {amount: 1}],
      ['d2', 'patch', {done: true}], ['n2', 'create', body({title: 'Valve'})],
      ['keep', 'patch', {assignee: 'Lee'}]]) {
      state = reduce(state, {type: 'QUEUE', mutation, id: mutation === 'n2' ? 'valve' : 'pump',
        kind, data});
    }
    await save(path, state);
    await assert.rejects(sendBatchOnce(path, 'close-1', 3, lost), /lost/);
    const batchWire = (await load(path)).batch.wire;
    const head = (await call('/pull?tenant=north&limit=100&checkpoint=0')).until;
    const compact = spawnSync('python3', ['tools/compact.py', '--db', db, '--through', head],
      {cwd: ROOT});
    assert.equal(compact.status, 0, String(compact.stderr));
    state = await load(path);
    const recovery = await call(`/pull?tenant=north&limit=1&checkpoint=${state.checkpoint}`)
      .catch(error => error);
    assert.equal(recovery.status, 410);
    assert.equal(recovery.json.detail.floor, head);
    await save(path, reduce(state, {type: 'RECOVERY_REQUIRED', epoch, floor: head}));
    await assert.rejects(sendBatchOnce(path, 'close-1', 3, lost));
    state = await bootstrap(call, path);
    assert.equal(state.needsSnapshot, false);
    assert.deepEqual(state.pending.map(p => p.mutation), ['keep']);
    assert.equal(selectView(state).records.find(r => r.id === 'pump').body.visits, 2);
    state = await sendBatchOnce(path, 'close-1', 3, wire => {
      assert.deepEqual(wire, batchWire);
      return call('/batch', wire);
    });
    assert.equal(state.batch, null);
    state = await sendOnce(path, wire => call('/mutate', wire));
    assert.equal(state.pending.length, 0);
    state = await catchUp(call, path);
    const view = selectView(state).records;
    assert.deepEqual(view.map(r => [r.id, r.body.visits, r.body.done, r.body.assignee]),
      [['pump', 2, true, 'Lee'], ['valve', 0, false, null]]);
    assert.equal(BigInt(state.checkpoint) > 9007199254740993n, true);
  } finally {
    child.kill();
    rmSync(dir, {recursive: true, force: true});
  }
});

test('review regressions: epochs, duplicate batch receipts, create bases', async () => {
  let s = run(fresh(), snap([rec('x', '3', '3')], '3'),
    {type: 'QUEUE', mutation: 'm', id: 'x', kind: 'patch', data: {done: true}}, {type: 'SEND'},
    {type: 'SNAPSHOT', page: {kind: 'snapshot', tenant: 'north', epoch: 'e-2', cut: '0',
      rows: [], confirmed: [], next_cursor: 'more'}});
  assert.throws(() => reduce(s, ack('m', rec('x', '4', '6'))), /epoch/);
  assert.throws(() => reduce(s, {type: 'CONFLICT', mutation: 'm', current: rec('x', '4', '6')}));

  const created = run(fresh(), {type: 'QUEUE', mutation: 'c', id: 'x', kind: 'create',
    data: body()}, {type: 'QUEUE', mutation: 'v', id: 'x', kind: 'visit', data: {amount: 1}},
  snap([rec('x', '3', '3')], '3'));
  assert.equal(reduce(created, {type: 'SEND'}).pending[0].wire.base, '0');
  assert.deepEqual(reduce(created, {type: 'SEND_BATCH', batch: 'b', count: 2})
    .batch.wire.operations.map(o => o.base), ['0', '1']);

  const respond = (batch, mutation, record) => ({type: 'ACK_BATCH', response: {ok: true,
    tenant: 'north', device: 'van-7', batch, responses: [{ok: true, tenant: 'north',
      device: 'van-7', mutation, record}]}});
  s = run(fresh(), snap([rec('x', '1', '1')], '1'),
    {type: 'QUEUE', mutation: 'a', id: 'x', kind: 'visit', data: {amount: 1}},
    {type: 'QUEUE', mutation: 'b', id: 'x', kind: 'visit', data: {amount: 1}},
    {type: 'SEND_BATCH', batch: 'b1', count: 1});
  const first = respond('b1', 'a', rec('x', '2', '2', {visits: 1}));
  s = run(s, first, {type: 'SEND_BATCH', batch: 'b2', count: 1});
  assert.deepEqual(reduce(s, first), s, 'delayed duplicate keeps the in-flight batch');
  s = run(s, respond('b2', 'b', rec('x', '3', '3', {visits: 2})), first);
  assert.equal(s.pending.length, 0);

  const dir = mkdtempSync(join(tmpdir(), 'recover-'));
  try {
    const path = join(dir, 'state.json');
    await save(path, reduce(run(fresh(), snap([], '1')), {type: 'RECOVERY_REQUIRED',
      epoch: EPOCH, floor: '5'}));
    await assert.rejects(sendOnce(path, () => assert.fail('no exchange')), /Snapshot required/);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});
