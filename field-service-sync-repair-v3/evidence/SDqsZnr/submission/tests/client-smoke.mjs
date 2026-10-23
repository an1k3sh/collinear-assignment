import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createReplica, reduce, selectView} from '../client/replica.mjs';

test('offline creation is visible before first connection', () => {
  const state = reduce(createReplica('north', 'van-7'), {type: 'QUEUE',
    mutation: 'first', id: 'order', kind: 'create',
    data: {title: 'Inspection', assignee: null, visits: 0, done: false}});
  assert.equal(selectView(state).records[0].body.title, 'Inspection');
});

// ---------------------------------------------------------------------------
// Regression coverage for the 2026-04-19 incident and protocol 2.1/2.2.
import {execFileSync, spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync, existsSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createServer} from 'node:net';
import {load, save, sendOnce, sendBatchOnce} from '../client/durable.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const EPOCH = 'e-1';
const body = (extra = {}) => ({title: 'Inspection', assignee: null, visits: 0, done: false, ...extra});
const rec = (id, revision, seq, extra = {}, deleted = false) =>
  ({id, revision: String(revision), seq: String(seq), body: body(extra), deleted});
const snap = (cut, rows, next_cursor = null, confirmed = [], epoch = EPOCH) =>
  ({kind: 'snapshot', tenant: 'north', epoch, cut: String(cut), rows, confirmed, next_cursor});
const pullPage = (from, after, until, events, confirmed = []) =>
  ({kind: 'events', tenant: 'north', epoch: EPOCH, from: String(from), after: String(after),
    until: String(until), events, confirmed});
const receipt = (mutation, record, device = 'van-7') =>
  ({ok: true, tenant: 'north', device, mutation, record});
const run = (state, ...actions) => actions.reduce(reduce, state);
const boot = (rows = [rec('pump', 1, 1)], cut = 1) =>
  reduce(createReplica('north', 'van-7'), {type: 'SNAPSHOT', page: snap(cut, rows)});
const queue = (mutation, id, kind, data) => ({type: 'QUEUE', mutation, id, kind, data});
const view = state => selectView(state).records;

test('incident trace keeps the later offline edit and the checkpoint', () => {
  const output = JSON.parse(execFileSync('node', [join(ROOT, 'client/trace.mjs')],
    {input: readFileSync(join(ROOT, 'incidents/client-actions.json'))}));
  const input = JSON.parse(readFileSync(join(ROOT, 'incidents/client-actions.json'), 'utf8'));
  const record = output.view.records.find(r => r.id === 'pump-17');
  assert.equal(record.body.visits, input.expected_visible.visits);
  assert.equal(record.body.assignee, input.expected_visible.assignee);
  assert.deepEqual(output.state.pending.map(p => p.mutation), input.expected_pending);
  assert.equal(output.state.checkpoint, input.expected_checkpoint);
});

test('trace runner rejects malformed actions', () => {
  assert.throws(() => execFileSync('node', [join(ROOT, 'client/trace.mjs')],
    {input: JSON.stringify({actions: [{type: 'BOGUS'}]}), stdio: 'pipe'}));
});

test('reducer never mutates its inputs', () => {
  const state = boot();
  const frozen = JSON.stringify(state);
  const action = queue('m', 'pump', 'patch', {done: true});
  const actionCopy = JSON.stringify(action);
  const next = reduce(reduce(state, action), {type: 'SEND'});
  next.pending[0].data.done = false;
  assert.equal(JSON.stringify(state), frozen);
  assert.equal(JSON.stringify(action), actionCopy);
});

test('send freezes one immutable wire and only for the first intent', () => {
  assert.throws(() => reduce(reduce(createReplica('north', 'van-7'),
    queue('a', 'pump', 'visit', {amount: 1})), {type: 'SEND'}));
  let state = run(boot(), queue('a', 'pump', 'visit', {amount: 1}),
    queue('b', 'pump', 'patch', {assignee: 'Mira'}), {type: 'SEND'});
  const wire = state.pending[0].wire;
  assert.deepEqual(wire, {tenant: 'north', device: 'van-7', mutation: 'a', id: 'pump',
    base: '1', kind: 'visit', data: {amount: 1}});
  assert.equal(state.pending[1].wire, undefined);
  state = run(state, {type: 'PUSH', epoch: EPOCH, record: rec('pump', 2, 5, {done: true})},
    {type: 'SEND'});
  assert.deepEqual(state.pending[0].wire, wire);
  assert.equal(state.pending[1].wire, undefined);
});

test('ACK removes only its intent and never rolls back newer records', () => {
  let state = run(boot(), queue('a', 'pump', 'visit', {amount: 1}),
    queue('b', 'pump', 'patch', {assignee: 'Mira'}), {type: 'SEND'},
    {type: 'PUSH', epoch: EPOCH, record: rec('pump', 3, 9, {visits: 1, done: true})},
    {type: 'ACK', response: receipt('a', rec('pump', 2, 7, {visits: 1}))});
  assert.deepEqual(state.pending.map(p => p.mutation), ['b']);
  assert.equal(state.base.pump.revision, '3');
  assert.equal(state.checkpoint, '1');
  const again = reduce(state, {type: 'ACK', response: receipt('a', rec('pump', 2, 7, {visits: 1}))});
  assert.deepEqual(again.pending.map(p => p.mutation), ['b']);
  assert.throws(() => reduce(state, {type: 'ACK',
    response: receipt('a', rec('pump', 2, 7, {visits: 1}), 'van-8')}));
  assert.throws(() => reduce(state, {type: 'ACK',
    response: receipt('a', rec('pump', 3, 9, {visits: 5}))}), /equal revision/);
  assert.throws(() => reduce(state, {type: 'ACK',
    response: receipt('never-sent', rec('pump', 3, 9, {visits: 1, done: true}))}), /unknown/);
  assert.throws(() => reduce(state, queue('a', 'pump', 'visit', {amount: 1})), /unique/);
  assert.throws(() => reduce(reduce(createReplica('north', 'van-7'), queue('m', 'p', 'delete', {})),
    {type: 'CONFLICT', mutation: 'm', current: null}));
});

test('push never advances the checkpoint and foreign epochs require a snapshot', () => {
  const state = reduce(boot(), {type: 'PUSH', epoch: EPOCH, record: rec('pump', 2, 50)});
  assert.equal(state.checkpoint, '1');
  assert.throws(() => reduce(state, {type: 'PUSH', epoch: 'e-2', record: rec('pump', 3, 51)}));
  assert.throws(() => reduce(createReplica('north', 'van-7'),
    {type: 'PUSH', epoch: EPOCH, record: rec('pump', 3, 51)}));
});

test('decimal strings beyond 2^53 compare exactly', () => {
  let state = boot([rec('pump', '9007199254740992', '9007199254740992')], '9007199254740992');
  state = reduce(state, {type: 'PUSH', epoch: EPOCH,
    record: rec('pump', '9007199254740993', '9007199254740993', {done: true})});
  assert.equal(state.base.pump.revision, '9007199254740993');
  state = reduce(state, {type: 'PULL', page: pullPage('9007199254740992', '9007199254740993',
    '9007199254740993', [])});
  assert.equal(state.checkpoint, '9007199254740993');
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snap('9007199254740992', [])}),
    /Backward/);
  state = run(state, queue('v', 'pump', 'visit', {amount: 1}),
    queue('w', 'pump', 'visit', {amount: 1}), {type: 'SEND_BATCH', batch: 'b', count: 2});
  assert.deepEqual(state.batch.wire.operations.map(op => op.base),
    ['9007199254740993', '9007199254740994']);
  assert.deepEqual(JSON.parse(JSON.stringify(state)), state);
});

test('snapshot pages stage atomically, drop stale entities and replay post-cut deliveries', () => {
  let state = boot([rec('a', 1, 1), rec('stale', 1, 1)], 1);
  state = run(state, queue('local', 'z', 'create', body({title: 'Offline'})),
    {type: 'SNAPSHOT', page: snap(10, [rec('a', 2, 8)], 'next')});
  assert.equal(state.base.a.revision, '1');
  assert.ok(state.base.stale);
  assert.equal(state.checkpoint, '1');
  assert.throws(() => reduce(state, {type: 'PULL', page: pullPage(1, 2, 2, [])}));
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snap(11, [], null)}), /Mixed/);
  assert.throws(() => reduce(state, {type: 'SNAPSHOT',
    page: snap(10, [rec('a', 2, 8, {done: true})], 'next2')}), /Mixed snapshot row/);
  state = run(state, {type: 'PUSH', epoch: EPOCH, record: rec('b', 1, 12)},
    {type: 'SNAPSHOT', page: snap(10, [rec('a', 2, 8)], 'next')},
    {type: 'SNAPSHOT', page: snap(10, [rec('c', 1, 9, {}, true)], null)});
  assert.deepEqual(Object.keys(state.base).sort(), ['a', 'b', 'c']);
  assert.equal(state.checkpoint, '10');
  assert.deepEqual(view(state).map(r => r.id), ['a', 'b', 'z']);
  const repeated = reduce(state, {type: 'SNAPSHOT', page: snap(10, [rec('c', 1, 9, {}, true)], null)});
  assert.deepEqual(repeated.base, state.base);
});

test('pull requires contiguity and treats consumed pages as duplicates', () => {
  let state = boot([rec('a', 1, 1)], 1);
  const first = pullPage(1, 3, 6, [rec('a', 2, 3)]);
  state = reduce(state, {type: 'PULL', page: first});
  assert.equal(state.checkpoint, '3');
  assert.deepEqual(reduce(state, {type: 'PULL', page: first}), state);
  assert.throws(() => reduce(state, {type: 'PULL', page: pullPage(4, 6, 6, [])}), /Noncontiguous/);
  assert.throws(() => reduce(state, {type: 'PULL', page: pullPage(3, 5, 6, [rec('a', 3, 6)])}));
  assert.throws(() => reduce(state, {type: 'PULL',
    page: {...pullPage(3, 5, 6, [rec('a', 3, 4)]), next_cursor: null}}), /until/);
  assert.throws(() => reduce(state, {type: 'PULL',
    page: {...pullPage(3, 5, 6, [rec('a', 3, 4)]), next_cursor: 'more'}}), /last event/);
  state = reduce(state, {type: 'PULL', page: pullPage(3, 6, 6, [])});
  assert.equal(state.checkpoint, '6');
});

test('pull confirmations retire sent intents but never unsent or foreign ones', () => {
  let state = run(boot(), queue('m-9', 'pump', 'visit', {amount: 1}),
    queue('m-10', 'pump', 'patch', {assignee: 'Mira'}), {type: 'SEND'});
  const committed = rec('pump', 2, 4, {visits: 1});
  const other = {device: 'van-8', mutation: 'm-10', id: 'pump', seq: '5'};
  state = reduce(state, {type: 'PULL', page: pullPage(1, 5, 5,
    [committed, rec('pump', 3, 5, {visits: 1, assignee: 'Lee'})],
    [{device: 'van-7', mutation: 'm-9', id: 'pump', seq: '4'}, other])});
  assert.deepEqual(state.pending.map(p => p.mutation), ['m-10']);
  assert.equal(view(state)[0].body.visits, 1);
  assert.equal(view(state)[0].body.assignee, 'Mira');
  assert.throws(() => reduce(state, {type: 'PULL', page: pullPage(5, 6, 6,
    [rec('pump', 4, 6)], [{device: 'van-7', mutation: 'm-10', id: 'pump', seq: '6'}])}), /unsent/);
  const sent = reduce(state, {type: 'SEND'});
  assert.throws(() => reduce(sent, {type: 'PULL', page: pullPage(5, 6, 6,
    [rec('other', 1, 6)], [{device: 'van-7', mutation: 'm-10', id: 'other', seq: '6'}])}),
  /entity/);
  const legacy = pullPage(5, 6, 6, []);
  delete legacy.confirmed;
  assert.equal(reduce(sent, {type: 'PULL', page: legacy}).checkpoint, '6');
  assert.equal(reduce(sent, {type: 'ACK', response: receipt('m-9', committed)}).pending.length, 1);
});

test('snapshot confirmations detect a committed visit superseded by later revisions', () => {
  let state = run(boot([rec('pump', 7, 7)], 7), queue('v', 'pump', 'visit', {amount: 1}),
    {type: 'SEND'}, queue('later', 'pump', 'patch', {assignee: 'Jo'}));
  state = run(state,
    {type: 'SNAPSHOT', page: snap(20, [rec('pump', 9, 15, {visits: 1, done: true})], null,
      [{device: 'van-7', mutation: 'v', id: 'pump', seq: '12'},
        {device: 'van-9', mutation: 'later', id: 'pump', seq: '15'}])});
  assert.deepEqual(state.pending.map(p => p.mutation), ['later']);
  assert.equal(view(state)[0].body.visits, 1);
  assert.equal(view(state)[0].body.assignee, 'Jo');
  const late = reduce(state, {type: 'ACK', response: receipt('v', rec('pump', 8, 12, {visits: 1}))});
  assert.equal(late.base.pump.revision, '9');
  assert.deepEqual(late.pending.map(p => p.mutation), ['later']);
});

test('conflicts block without retry and resolve explicitly', () => {
  let state = run(boot(), queue('a', 'pump', 'patch', {done: true}),
    queue('b', 'pump', 'patch', {assignee: 'X'}), {type: 'SEND'});
  const wire = state.pending[0].wire;
  state = reduce(state, {type: 'CONFLICT', mutation: 'a', current: rec('pump', 2, 3, {visits: 4})});
  assert.deepEqual(state.pending[0].wire, wire);
  assert.deepEqual(selectView(state).conflicts, ['a']);
  assert.equal(reduce(state, {type: 'SEND'}).pending[0].wire.mutation, 'a');
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'b', mode: 'drop'}));
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'a', mode: 'retry', newMutation: 'b'}));
  state = run(state, {type: 'RESOLVE', mutation: 'a', mode: 'retry', newMutation: 'a2'}, {type: 'SEND'});
  assert.equal(state.pending[0].wire.base, '2');
  assert.equal(state.pending[0].wire.mutation, 'a2');
});

test('view does not let ordinary edits revive deleted or missing entities', () => {
  const state = run(boot([rec('gone', 2, 1, {}, true)], 1),
    queue('p', 'gone', 'patch', {done: true}), queue('q', 'missing', 'visit', {amount: 1}),
    queue('r', 'gone', 'restore', {assignee: 'Ana'}), queue('c', 'gone', 'create', body()));
  const result = selectView(state);
  assert.deepEqual(result.conflicts, ['p', 'q', 'c']);
  assert.deepEqual(result.records.map(r => [r.id, r.body.assignee]), [['gone', 'Ana']]);
});

test('batch send freezes predicted bases and survives partial confirmation', () => {
  let state = run(boot([rec('pump', 7, 7), rec('valve', 3, 6)], 7),
    queue('v', 'pump', 'visit', {amount: 1}), queue('d', 'pump', 'patch', {done: true}),
    queue('n', 'new', 'create', body()), queue('x', 'valve', 'patch', {done: true}),
    queue('later', 'valve', 'patch', {assignee: 'Q'}));
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'c', count: 17}));
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'c', count: 6}));
  state = reduce(state, {type: 'SEND_BATCH', batch: 'c', count: 4});
  const wire = state.batch.wire;
  assert.deepEqual(wire.operations.map(op => [op.mutation, op.base]),
    [['v', '7'], ['d', '8'], ['n', '0'], ['x', '3']]);
  assert.throws(() => reduce(state, {type: 'SEND'}), /batch/);
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'other', count: 4}));
  assert.throws(() => reduce(state, {type: 'CONFLICT', mutation: 'd', current: null}));
  const responses = [receipt('v', rec('pump', 8, 10, {visits: 1})),
    receipt('d', rec('pump', 9, 11, {visits: 1, done: true})),
    receipt('n', rec('new', 1, 12)), receipt('x', rec('valve', 4, 13, {done: true}))];
  state = run(state, {type: 'PUSH', epoch: EPOCH, record: rec('valve', 5, 14, {done: true, assignee: 'Z'})},
    {type: 'PULL', page: pullPage(7, 10, 14, [responses[0].record],
      [{device: 'van-7', mutation: 'v', id: 'pump', seq: '10'}])});
  assert.deepEqual(state.pending.map(p => p.mutation), ['d', 'n', 'x', 'later']);
  assert.deepEqual(reduce(state, {type: 'SEND_BATCH', batch: 'c', count: 4}).batch.wire, wire);
  const ack = {ok: true, tenant: 'north', device: 'van-7', batch: 'c', responses};
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...ack, responses: responses.slice(0, 3)}}));
  assert.throws(() => reduce(state, {type: 'ACK_BATCH',
    response: {...ack, responses: [responses[1], responses[0], ...responses.slice(2)]}}));
  state = reduce(state, {type: 'ACK_BATCH', response: ack});
  assert.equal(state.batch, null);
  assert.deepEqual(state.pending.map(p => p.mutation), ['later']);
  assert.equal(state.base.valve.revision, '5');
  assert.deepEqual(reduce(state, {type: 'ACK_BATCH', response: ack}), state);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...ack, batch: 'zzz'}}));
});

test('recovery keeps the outbox and requires a snapshot at or beyond the floor', () => {
  let state = run(boot([rec('pump', 2, 2)], 2), queue('v', 'pump', 'visit', {amount: 1}),
    queue('w', 'pump', 'visit', {amount: 1}), {type: 'SEND_BATCH', batch: 'b', count: 1},
    queue('later', 'pump', 'patch', {assignee: 'K'}),
    {type: 'SNAPSHOT', page: snap(30, [], 'more')});
  const wire = state.batch.wire;
  assert.throws(() => reduce(state, {type: 'RECOVERY_REQUIRED', epoch: 'e-9', floor: '20'}));
  state = run(state, {type: 'RECOVERY_REQUIRED', epoch: EPOCH, floor: '20'},
    {type: 'RECOVERY_REQUIRED', epoch: EPOCH, floor: '10'});
  assert.equal(state.needsSnapshot, true);
  assert.equal(state.recoveryFloor, '20');
  assert.equal(state.snapshot, null);
  assert.equal(state.checkpoint, '2');
  assert.deepEqual(state.batch.wire, wire);
  assert.deepEqual(state.pending.map(p => p.mutation), ['v', 'w', 'later']);
  for (const action of [{type: 'SEND'}, {type: 'SEND_BATCH', batch: 'b', count: 1},
    {type: 'PULL', page: pullPage(2, 3, 3, [])}]) assert.throws(() => reduce(state, action));
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snap(19, [])}), /recovery floor/);
  state = run(state, queue('q', 'pump', 'patch', {done: true}),
    {type: 'PUSH', epoch: EPOCH, record: rec('pump', 5, 40, {visits: 1})});
  assert.equal(state.needsSnapshot, true);
  state = run(state, {type: 'SNAPSHOT', page: snap(25, [rec('pump', 4, 24, {visits: 1})], null,
    [{device: 'van-7', mutation: 'v', id: 'pump', seq: '21'}])});
  assert.equal(state.needsSnapshot, false);
  assert.equal(state.recoveryFloor, null);
  assert.equal(state.checkpoint, '25');
  assert.equal(state.base.pump.revision, '5');
  assert.deepEqual(state.pending.map(p => p.mutation), ['w', 'later', 'q']);
  assert.deepEqual(reduce(state, {type: 'SEND_BATCH', batch: 'b', count: 1}).batch.wire, wire);
});

test('durable save is atomic and load requires an existing file', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'replica-'));
  try {
    const path = join(directory, 'state.json');
    await assert.rejects(load(path));
    await save(path, boot());
    await assert.rejects(save(path, {broken: true}, async point => {
      assert.equal(point, 'before_rename');
      throw new Error('crash');
    }), /crash/);
    assert.deepEqual(await load(path), boot());
    assert.deepEqual(readdirSync(directory), ['state.json']);
  } finally {
    rmSync(directory, {recursive: true, force: true});
  }
});

test('sendOnce persists the wire before a lost response and retries identically', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'replica-'));
  try {
    const path = join(directory, 'state.json');
    await save(path, run(boot(), queue('m-9', 'pump', 'visit', {amount: 1}),
      queue('m-10', 'pump', 'patch', {assignee: 'Mira'})));
    const seen = [];
    await assert.rejects(sendOnce(path, async wire => {
      seen.push(wire);
      assert.deepEqual((await load(path)).pending[0].wire, wire);
      throw new Error('lost response');
    }));
    await save(path, reduce(await load(path), {type: 'PUSH', epoch: EPOCH, record: rec('pump', 3, 9)}));
    const result = await sendOnce(path, async wire => {
      seen.push(wire);
      return receipt('m-9', rec('pump', 2, 5, {visits: 1}));
    });
    assert.deepEqual(seen[0], seen[1]);
    assert.deepEqual(result.pending.map(p => p.mutation), ['m-10']);
    assert.deepEqual(await load(path), result);
    const blocked = reduce(reduce(result, {type: 'SEND'}),
      {type: 'CONFLICT', mutation: 'm-10', current: null});
    await save(path, blocked);
    assert.deepEqual(await sendOnce(path, () => assert.fail('no exchange')), blocked);
  } finally {
    rmSync(directory, {recursive: true, force: true});
  }
});

test('sendBatchOnce retries the stored full wire after members were retired', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'replica-'));
  try {
    const path = join(directory, 'state.json');
    await save(path, run(boot(), queue('a', 'pump', 'visit', {amount: 1}),
      queue('b', 'pump', 'patch', {done: true}), queue('c', 'pump', 'patch', {assignee: 'L'})));
    const seen = [];
    await assert.rejects(sendBatchOnce(path, 'close', 2, async wire => {
      seen.push(wire);
      throw new Error('lost');
    }));
    const records = [rec('pump', 2, 2, {visits: 1}), rec('pump', 3, 3, {visits: 1, done: true})];
    await save(path, reduce(await load(path), {type: 'SNAPSHOT', page: snap(3, [records[1]], null,
      [{device: 'van-7', mutation: 'a', id: 'pump', seq: '2'},
        {device: 'van-7', mutation: 'b', id: 'pump', seq: '3'}])}));
    assert.deepEqual((await load(path)).pending.map(p => p.mutation), ['c']);
    await assert.rejects(sendOnce(path, () => assert.fail('no exchange')), /batch/);
    const result = await sendBatchOnce(path, 'close', 2, async wire => {
      seen.push(wire);
      return {ok: true, tenant: 'north', device: 'van-7', batch: 'close',
        responses: [receipt('a', records[0]), receipt('b', records[1])]};
    });
    assert.deepEqual(seen[1], seen[0]);
    assert.equal(seen[0].operations.length, 2);
    assert.equal(result.batch, null);
    assert.deepEqual(result.pending.map(p => p.mutation), ['c']);
  } finally {
    rmSync(directory, {recursive: true, force: true});
  }
});

async function freePort() {
  return new Promise(resolve => {
    const server = createServer().listen(0, '127.0.0.1', () => {
      const {port} = server.address();
      server.close(() => resolve(port));
    });
  });
}

test('end to end: replica against the HTTP service with lost responses and compaction', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'e2e-'));
  const db = join(directory, 'site.sqlite');
  const port = await freePort();
  const server = spawn('python3', ['-m', 'server.http', '--db', db, '--port', String(port)],
    {cwd: ROOT, stdio: 'ignore'});
  const base = `http://127.0.0.1:${port}`;
  const call = async (path, payload) => {
    const response = await fetch(base + path, payload === undefined ? {} :
      {method: 'POST', body: JSON.stringify(payload)});
    return {status: response.status, json: await response.json()};
  };
  try {
    for (let i = 0; i < 100; i++) {
      try { await fetch(`${base}/health`); break; } catch { await new Promise(r => setTimeout(r, 50)); }
    }
    const bootstrap = async state => {
      let cursor = null;
      do {
        const page = (await call(`/snapshot?tenant=north&limit=1${cursor ? `&cursor=${cursor}` : ''}`)).json;
        state = reduce(state, {type: 'SNAPSHOT', page});
        cursor = page.next_cursor;
      } while (cursor);
      return state;
    };
    const catchUp = async state => {
      const checkpoint = state.checkpoint;
      let cursor = null;
      do {
        const {status, json} = await call(`/pull?tenant=north&limit=1&checkpoint=${checkpoint}${cursor ? `&cursor=${cursor}` : ''}`);
        if (status === 410) return reduce(state, {type: 'RECOVERY_REQUIRED', ...json.detail});
        state = reduce(state, {type: 'PULL', page: json});
        cursor = json.next_cursor;
      } while (cursor);
      return state;
    };
    await call('/mutate', {tenant: 'north', device: 'desk', mutation: 'seed', id: 'pump',
      base: '0', kind: 'create', data: body({title: 'Pumpe ✓'})});
    const path = join(directory, 'van.json');
    let state = await bootstrap(createReplica('north', 'van-7'));
    state = run(state, queue('v', 'pump', 'visit', {amount: 1}), queue('d', 'pump', 'patch', {done: true}),
      queue('later', 'pump', 'patch', {assignee: 'Mira'}));
    await save(path, state);
    await assert.rejects(sendBatchOnce(path, 'close', 2, async wire => {
      await call('/batch', wire);
      throw new Error('access point lost the response');
    }));
    await call('/mutate', {tenant: 'north', device: 'desk', mutation: 'x', id: 'other',
      base: '0', kind: 'create', data: body()});
    execFileSync('python3', [join(ROOT, 'tools/compact.py'), '--db', db, '--through', '4']);
    state = await catchUp(await load(path));
    assert.equal(state.needsSnapshot, true);
    state = await bootstrap(state);
    assert.deepEqual(state.pending.map(p => p.mutation), ['later']);
    const pump = selectView(state).records.find(r => r.id === 'pump');
    assert.deepEqual([pump.body.visits, pump.body.done, pump.body.assignee], [1, true, 'Mira']);
    await save(path, state);
    state = await sendBatchOnce(path, 'close', 2, async wire => (await call('/batch', wire)).json);
    assert.equal(state.batch, null);
    state = await sendOnce(path, async wire => (await call('/mutate', wire)).json);
    assert.deepEqual(state.pending, []);
    state = await catchUp(state);
    assert.equal(state.base.pump.body.assignee, 'Mira');
    assert.equal(state.base.pump.body.visits, 1);
    assert.equal(state.checkpoint, '5');
  } finally {
    server.kill();
    rmSync(directory, {recursive: true, force: true});
  }
});
