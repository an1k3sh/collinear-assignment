import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync} from 'node:fs';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createReplica, reduce, selectView} from '../client/replica.mjs';
import {load, save, sendBatchOnce, sendOnce} from '../client/durable.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const EPOCH = 'dispatch-2026-04';
const S = n => (9007199254740990n + BigInt(n)).toString(); // beyond 2^53
const body = (extra = {}) => ({title: 'Pump', assignee: null, visits: 0, done: false, ...extra});
const rec = (id, revision, seq, extra = {}, deleted = false) =>
  ({id, revision: String(revision), seq: S(seq), body: body(extra), deleted});
const snap = (rows, cut, extra = {}) => ({type: 'SNAPSHOT', page: {kind: 'snapshot',
  tenant: 'north', epoch: EPOCH, cut: S(cut), rows, next_cursor: null, ...extra}});
const pull = (from, after, events, extra = {}) => ({type: 'PULL', page: {kind: 'events',
  tenant: 'north', epoch: EPOCH, from: S(from), after: S(after), until: S(after), events,
  next_cursor: null, ...extra}});
const ack = (mutation, record, device = 'van-7') =>
  ({type: 'ACK', response: {ok: true, tenant: 'north', device, mutation, record}});
const queue = (mutation, id, kind, data) => ({type: 'QUEUE', mutation, id, kind, data});
const run = (actions, state = createReplica('north', 'van-7')) =>
  actions.reduce((s, a) => reduce(s, a), state);
const mutations = state => state.pending.map(p => p.mutation);

test('offline creation is visible before first connection', () => {
  const state = reduce(createReplica('north', 'van-7'), {type: 'QUEUE',
    mutation: 'first', id: 'order', kind: 'create',
    data: {title: 'Inspection', assignee: null, visits: 0, done: false}});
  assert.equal(selectView(state).records[0].body.title, 'Inspection');
});

test('incident trace: delayed ACK removes only its own intent', () => {
  const input = readFileSync(join(ROOT, 'incidents/client-actions.json'), 'utf8');
  const result = spawnSync(process.execPath, [join(ROOT, 'client/trace.mjs')], {input});
  assert.equal(result.status, 0, result.stderr.toString());
  const {state, view} = JSON.parse(result.stdout);
  const expected = JSON.parse(input);
  assert.deepEqual(mutations(state), expected.expected_pending);
  assert.equal(state.checkpoint, expected.expected_checkpoint);
  assert.equal(view.records[0].body.visits, expected.expected_visible.visits);
  assert.equal(view.records[0].body.assignee, expected.expected_visible.assignee);
  const bad = spawnSync(process.execPath, [join(ROOT, 'client/trace.mjs')],
    {input: JSON.stringify({actions: [{type: 'PULL', page: {}}]})});
  assert.notEqual(bad.status, 0);
  assert.match(bad.stderr.toString(), /trace failed/);
});

test('reducer is pure and keeps large decimals exact', () => {
  const start = run([snap([rec('a', 1, 3)], 3)]);
  const frozen = JSON.stringify(start);
  const next = reduce(start, {type: 'PUSH', epoch: EPOCH, record: rec('a', 2, 4)});
  assert.equal(JSON.stringify(start), frozen);
  assert.equal(next.base.a.seq, '9007199254740994');
  assert.throws(() => reduce(start, {type: 'PUSH', epoch: EPOCH,
    record: {...rec('a', 2, 4), seq: 9007199254740994}}));
  // Revisions differing only beyond 2^53 still order correctly.
  const big = run([{type: 'PUSH', epoch: EPOCH, record: {...rec('a', 0, 5), revision: S(3)}},
    {type: 'PUSH', epoch: EPOCH, record: {...rec('a', 0, 6, {visits: 1}), revision: S(4)}},
    {type: 'PUSH', epoch: EPOCH, record: {...rec('a', 0, 4), revision: S(2)}}], start);
  assert.equal(big.base.a.revision, S(4));
});

test('push never advances checkpoint; other epochs need a snapshot', () => {
  const state = run([snap([], 10), {type: 'PUSH', epoch: EPOCH, record: rec('z', 1, 20)}]);
  assert.equal(state.checkpoint, S(10));
  assert.equal(state.base.z.revision, '1');
  assert.throws(() => reduce(state, {type: 'PUSH', epoch: 'other', record: rec('y', 1, 21)}));
  assert.throws(() => reduce(state, pull(15, 20, [])), /Noncontiguous/);
  assert.throws(() => reduce(createReplica('north', 'v'),
    {type: 'PUSH', epoch: EPOCH, record: rec('y', 1, 21)}));
});

test('pull pages are contiguous and duplicates are idempotent', () => {
  let state = run([snap([], 10), pull(10, 12, [rec('a', 1, 11)])]);
  const again = reduce(state, pull(10, 12, [rec('a', 1, 11)]));
  assert.deepEqual(again, state);
  assert.throws(() => reduce(state, pull(13, 14, [])), /Noncontiguous/);
  assert.throws(() => reduce(state, pull(12, 14, [rec('b', 1, 15)])), /outside/);
  state = reduce(state, pull(12, 20, []));
  assert.equal(state.checkpoint, S(20));
});

test('snapshot staging: partial pages do not touch base; completion drops stale rows', () => {
  let state = run([snap([rec('old', 1, 1), rec('keep', 1, 2)], 5),
    queue('m-1', 'keep', 'patch', {done: true})]);
  const page1 = {kind: 'snapshot', tenant: 'north', epoch: EPOCH, cut: S(30),
    rows: [rec('keep', 2, 20)], next_cursor: 'c1'};
  state = reduce(state, {type: 'SNAPSHOT', page: page1});
  assert.deepEqual(Object.keys(state.base).sort(), ['keep', 'old']);
  assert.equal(state.checkpoint, S(5));
  assert.throws(() => reduce(state, pull(5, 6, [])));
  // Push during staging buffers; it is newer than the cut.
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('new', 1, 31)});
  state = reduce(state, {type: 'SNAPSHOT', page: page1}); // retried identical page
  assert.throws(() => reduce(state, {type: 'SNAPSHOT',
    page: {...page1, rows: [rec('keep', 3, 21)]}}), /Mixed/);
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: {...page1, cut: S(31)}}), /Mixed/);
  state = reduce(state, {type: 'SNAPSHOT', page: {...page1, rows: [rec('zed', 1, 3)],
    next_cursor: null}});
  assert.deepEqual(Object.keys(state.base).sort(), ['keep', 'new', 'zed']);
  assert.equal(state.checkpoint, S(30));
  assert.deepEqual(mutations(state), ['m-1']);
  assert.throws(() => reduce(state, snap([], 29)), /Backward/);
});

test('view: ordinary edits cannot revive tombstones; restore can', () => {
  const state = run([snap([rec('a', 2, 3, {}, true), rec('b', 1, 2)], 3),
    queue('p', 'a', 'patch', {done: true}), queue('v', 'missing', 'visit', {amount: 1}),
    queue('r', 'a', 'restore', {assignee: 'Kai'}), queue('d', 'b', 'delete', {})]);
  const view = selectView(state);
  assert.deepEqual(view.conflicts, ['p', 'v']);
  assert.deepEqual(view.records.map(r => [r.id, r.body.assignee]), [['a', 'Kai']]);
});

test('conflict blocks; resolve retry recaptures base; IDs stay unique', () => {
  let state = run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'patch', {done: true}),
    {type: 'SEND'}, queue('m2', 'a', 'visit', {amount: 1})]);
  const wire = state.pending[0].wire;
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('a', 2, 2, {visits: 5})});
  assert.deepEqual(reduce(state, {type: 'SEND'}).pending[0].wire, wire);
  state = reduce(state, {type: 'CONFLICT', mutation: 'm1', current: rec('a', 2, 2, {visits: 5})});
  assert.deepEqual(state.pending[0].wire, wire);
  assert.deepEqual(selectView(state).conflicts, ['m1']);
  assert.deepEqual(reduce(state, {type: 'SEND'}), state);
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'm1', mode: 'retry',
    newMutation: 'm2'}));
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'm2', mode: 'drop'}));
  state = reduce(state, {type: 'RESOLVE', mutation: 'm1', mode: 'retry', newMutation: 'm1b'});
  state = reduce(state, {type: 'SEND'});
  assert.equal(state.pending[0].wire.base, '2');
  assert.equal(state.pending[0].wire.mutation, 'm1b');
});

test('ACK is matched by mutation; duplicate and foreign ACKs are safe', () => {
  let state = run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'visit', {amount: 1}),
    {type: 'SEND'}, queue('m2', 'a', 'visit', {amount: 2})]);
  assert.throws(() => reduce(state, ack('m1', rec('a', 2, 5, {visits: 1}), 'van-8')));
  assert.throws(() => reduce(state, ack('m2', rec('a', 2, 5, {visits: 1}))), /unsent/);
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('a', 3, 6, {visits: 1, done: true})});
  state = reduce(state, ack('m1', rec('a', 2, 5, {visits: 1})));
  assert.equal(state.base.a.revision, '3'); // delayed ACK does not roll back
  assert.deepEqual(mutations(state), ['m2']);
  assert.equal(selectView(state).records[0].body.visits, 3);
  assert.deepEqual(reduce(state, ack('m1', rec('a', 2, 5, {visits: 1}))).pending, state.pending);
  assert.equal(state.checkpoint, S(1));
});

test('pull confirmations retire lost-response intents exactly once', () => {
  let state = run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'visit', {amount: 1}),
    {type: 'SEND'}, queue('m2', 'a', 'patch', {assignee: 'Mira'})]);
  const confirmed = [{device: 'van-8', mutation: 'm2', id: 'a', seq: S(2)},
    {device: 'van-7', mutation: 'm1', id: 'a', seq: S(3)}];
  const page = pull(1, 3, [rec('a', 2, 2, {assignee: 'Lee'}), rec('a', 3, 3, {visits: 1, assignee: 'Lee'})],
    {confirmed});
  state = reduce(state, page);
  assert.deepEqual(mutations(state), ['m2']);
  const view = selectView(state).records[0].body;
  assert.equal(view.visits, 1);
  assert.equal(view.assignee, 'Mira');
  // Delayed ACK after confirmation is harmless; duplicate page does not act on new work.
  state = reduce(state, ack('m1', rec('a', 3, 3, {visits: 1, assignee: 'Lee'})));
  assert.deepEqual(reduce(state, page), state);
  const unsent = run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'visit', {amount: 1})]);
  assert.throws(() => reduce(unsent, pull(1, 2, [rec('a', 2, 2, {visits: 1})],
    {confirmed: [{device: 'van-7', mutation: 'm1', id: 'a', seq: S(2)}]})), /unsent/);
  const sent = reduce(unsent, {type: 'SEND'});
  assert.throws(() => reduce(sent, pull(1, 2, [rec('b', 1, 2)],
    {confirmed: [{device: 'van-7', mutation: 'm1', id: 'b', seq: S(2)}]})), /entity/);
});

test('snapshot confirmations identify a visit superseded by later revisions', () => {
  let state = run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'visit', {amount: 1}),
    {type: 'SEND'}, queue('m2', 'a', 'patch', {done: true})]);
  const page = {kind: 'snapshot', tenant: 'north', epoch: EPOCH, cut: S(9),
    rows: [rec('a', 3, 8, {visits: 1, assignee: 'Lee'})], next_cursor: 'p2',
    confirmed: [{device: 'van-7', mutation: 'm1', id: 'a', seq: S(4)}]};
  state = reduce(state, {type: 'SNAPSHOT', page});
  assert.deepEqual(mutations(state), ['m1', 'm2']); // not applied until completion
  state = reduce(state, {type: 'SNAPSHOT', page: {...page, rows: [], confirmed: [],
    next_cursor: null}});
  assert.deepEqual(mutations(state), ['m2']);
  assert.equal(selectView(state).records[0].body.visits, 1);
});

test('batch closeout: frozen wire, partial confirmation, full ACK', () => {
  let state = run([snap([rec('pump', 7, 1), rec('valve', 3, 2)], 2),
    queue('v', 'pump', 'visit', {amount: 1}), queue('d', 'pump', 'patch', {done: true}),
    queue('x', 'valve', 'patch', {done: true}), queue('later', 'valve', 'patch', {assignee: 'Q'})]);
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'b', count: 5}));
  state = reduce(state, {type: 'SEND_BATCH', batch: 'b', count: 3});
  const wire = state.batch.wire;
  assert.deepEqual(wire.operations.map(o => o.base), ['7', '8', '3']);
  assert.throws(() => reduce(state, {type: 'SEND'}));
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'c', count: 3}));
  assert.throws(() => reduce(state, {type: 'CONFLICT', mutation: 'd', current: null}));
  const r1 = {ok: true, tenant: 'north', device: 'van-7', mutation: 'v', record: rec('pump', 8, 3, {visits: 1})};
  const r2 = {ok: true, tenant: 'north', device: 'van-7', mutation: 'd', record: rec('pump', 9, 4, {visits: 1, done: true})};
  const r3 = {ok: true, tenant: 'north', device: 'van-7', mutation: 'x', record: rec('valve', 4, 5, {done: true})};
  // Pull page boundary falls inside the committed closeout.
  state = reduce(state, pull(2, 3, [r1.record], {confirmed: [{device: 'van-7', mutation: 'v', id: 'pump', seq: S(3)}]}));
  assert.deepEqual(mutations(state), ['d', 'x', 'later']);
  assert.equal(selectView(state).records[0].body.visits, 1);
  assert.deepEqual(reduce(state, {type: 'SEND_BATCH', batch: 'b', count: 3}).batch.wire, wire);
  const response = {ok: true, tenant: 'north', device: 'van-7', batch: 'b', responses: [r1, r2, r3]};
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response, responses: [r1, r3, r2]}}));
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response, responses: [r1, r2]}}));
  state = reduce(state, {type: 'ACK_BATCH', response});
  assert.equal(state.batch, null);
  assert.deepEqual(mutations(state), ['later']);
  assert.equal(state.base.pump.revision, '9');
  assert.deepEqual(reduce(state, {type: 'ACK_BATCH', response}), state);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response, batch: 'z'}}));
});

test('pull page boundaries and confirmations must match returned events', () => {
  const state = run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'visit', {amount: 1}),
    {type: 'SEND'}]);
  // Continuation must end at its last event; final page must end at until.
  assert.throws(() => reduce(state, pull(1, 5, [rec('a', 2, 2, {visits: 1})],
    {until: S(9), next_cursor: 'c'})), /boundary/);
  assert.throws(() => reduce(state, pull(1, 5, [], {until: S(9)})), /boundary/);
  // A confirmation without its event cannot retire durable work.
  assert.throws(() => reduce(state, pull(1, 5, [],
    {confirmed: [{device: 'van-7', mutation: 'm1', id: 'a', seq: S(2)}]})), /Confirmations/);
  const snapPage = {kind: 'snapshot', tenant: 'north', epoch: EPOCH, cut: S(5), rows: [],
    next_cursor: null, confirmed: [{device: 'van-7', mutation: 'm1', id: 'a', seq: S(2)}]};
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snapPage}), /outside this page/);
  // Legacy pages without `confirmed` are accepted.
  assert.equal(reduce(state, pull(1, 5, [])).checkpoint, S(5));
});

test('completed snapshot replay after checkpoint advanced is rejected as backward', () => {
  const first = snap([rec('a', 1, 1)], 10);
  const state = run([first, pull(10, 20, [])]);
  assert.throws(() => reduce(state, first), /Backward/);
  assert.deepEqual(reduce(run([first]), first), run([first]));
});

test('delayed duplicate ACK_BATCH stays idempotent after a later batch', () => {
  const receipt = (mutation, record) => ({ok: true, tenant: 'north', device: 'van-7', mutation, record});
  let state = run([snap([rec('a', 1, 1)], 1), queue('x', 'a', 'visit', {amount: 1}),
    queue('y', 'a', 'visit', {amount: 1}), {type: 'SEND_BATCH', batch: 'A', count: 1}]);
  const ackA = {ok: true, tenant: 'north', device: 'van-7', batch: 'A',
    responses: [receipt('x', rec('a', 2, 2, {visits: 1}))]};
  state = reduce(state, {type: 'ACK_BATCH', response: ackA});
  state = reduce(state, {type: 'SEND_BATCH', batch: 'B', count: 1});
  state = reduce(state, {type: 'ACK_BATCH', response: {...ackA, batch: 'B',
    responses: [receipt('y', rec('a', 3, 3, {visits: 2}))]}});
  assert.deepEqual(reduce(state, {type: 'ACK_BATCH', response: ackA}), state);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...ackA,
    responses: [receipt('x', rec('a', 2, 9, {visits: 1}))]}}));
  assert.throws(() => reduce(reduce(state, queue('z', 'a', 'visit', {amount: 1})),
    {type: 'SEND_BATCH', batch: 'A', count: 1}), /already acknowledged/);
});

test('durable save is atomic and load requires a file', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'replica-'));
  try {
    const path = join(dir, 'state.json');
    await assert.rejects(load(path));
    const first = createReplica('north', 'van-7');
    await save(path, first);
    const next = reduce(first, queue('m', 'a', 'create', body()));
    await assert.rejects(save(path, next, async point => {
      assert.equal(point, 'before_rename');
      throw new Error('crash');
    }));
    assert.deepEqual(await load(path), first);
    assert.deepEqual(readdirSync(dir), ['state.json']);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});

test('sendOnce persists the wire before exchange and retries it identically', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'replica-'));
  try {
    const path = join(dir, 'state.json');
    await save(path, run([snap([rec('a', 1, 1)], 1), queue('m1', 'a', 'visit', {amount: 1}),
      queue('m2', 'a', 'patch', {assignee: 'X'})]));
    const sent = [];
    await assert.rejects(sendOnce(path, async wire => {
      sent.push(wire);
      assert.deepEqual((await load(path)).pending[0].wire, wire);
      throw new Error('response lost');
    }));
    const state = await sendOnce(path, async wire => {
      sent.push(wire);
      return {ok: true, tenant: 'north', device: 'van-7', mutation: 'm1', record: rec('a', 2, 2, {visits: 1})};
    });
    assert.deepEqual(sent[0], sent[1]);
    assert.deepEqual(mutations(state), ['m2']);
    assert.deepEqual(await load(path), state);
    let called = false;
    await save(path, reduce(state, {type: 'CONFLICT', mutation: 'm2', current: null}));
    await sendOnce(path, async () => { called = true; });
    assert.equal(called, false);
  } finally {
    rmSync(dir, {recursive: true, force: true});
  }
});

// ---------------------------------------------------------------- end to end

async function freePort() {
  return new Promise(resolve => {
    const server = createServer().listen(0, '127.0.0.1', () => {
      const {port} = server.address();
      server.close(() => resolve(port));
    });
  });
}

async function startServer(db) {
  const port = await freePort();
  const proc = spawn('python3', ['-m', 'server.http', '--db', db, '--port', String(port)],
    {cwd: ROOT, stdio: 'ignore'});
  const base = `http://127.0.0.1:${port}`;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch(`${base}/health`)).ok) break; } catch { /* starting */ }
    await new Promise(r => setTimeout(r, 50));
  }
  const call = async (path, payload) => {
    const response = await fetch(`${base}${path}`, payload === undefined ? {} : {
      method: 'POST', body: JSON.stringify(payload), headers: {'content-type': 'application/json'}});
    const json = await response.json();
    if (!response.ok) throw Object.assign(new Error(json.code), {response: json});
    return json;
  };
  return {proc, call};
}

async function catchUp(path, call, mode = 'pull', limit = 1) {
  let state = await load(path);
  if (mode === 'snapshot') {
    let cursor = null;
    do {
      const page = await call(`/snapshot?tenant=north&limit=${limit}${cursor ? `&cursor=${cursor}` : ''}`);
      state = reduce(state, {type: 'SNAPSHOT', page});
      cursor = page.next_cursor;
    } while (cursor);
  } else {
    const origin = state.checkpoint;
    let cursor = null;
    do {
      const page = await call(`/pull?tenant=north&limit=${limit}&checkpoint=${origin}${cursor ? `&cursor=${cursor}` : ''}`);
      state = reduce(state, {type: 'PULL', page});
      cursor = page.next_cursor;
    } while (cursor);
  }
  await save(path, state);
  return state;
}

test('end to end: lost single and batch receipts against the HTTP server', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'e2e-'));
  const db = join(dir, 'site.sqlite');
  spawnSync('python3', [join(ROOT, 'tools/seed.py'), '--db', db]);
  const {proc, call} = await startServer(db);
  try {
    const path = join(dir, 'van7.json');
    await save(path, createReplica('north', 'van-7'));
    await catchUp(path, call, 'snapshot', 1);
    assert.equal((await load(path)).base['valve-4'].deleted, true);
    for (const action of [queue('m-9', 'pump-17', 'visit', {amount: 1}),
      queue('m-10', 'pump-17', 'patch', {assignee: 'Mira'})]) {
      await save(path, reduce(await load(path), action));
    }
    // Commit happens, response lost; restart; retry gets the original receipt.
    await assert.rejects(sendOnce(path, async wire => { await call('/mutate', wire); throw new Error('lost'); }));
    let state = await sendOnce(path, wire => call('/mutate', wire));
    assert.deepEqual(mutations(state), ['m-10']);
    assert.equal(selectView(state).records[0].body.visits, 10);
    // Other van, same mutation ID.
    const other = await call('/mutate', {tenant: 'north', device: 'van-8', mutation: 'm-9',
      id: 'pump-17', base: '44', kind: 'patch', data: {done: false}});
    assert.equal(other.device, 'van-8');
    // m-10 freezes base 44 on first send, so it conflicts with van-8's edit.
    state = reduce(await load(path), {type: 'SEND'});
    await save(path, state);
    const rejected = await call('/mutate', state.pending[0].wire).catch(e => e.response);
    assert.equal(rejected.code, 'conflict');
    state = reduce(state, {type: 'CONFLICT', mutation: 'm-10', current: rejected.detail.current});
    state = reduce(state, {type: 'RESOLVE', mutation: 'm-10', mode: 'retry', newMutation: 'm-10b'});
    await save(path, state);
    state = await sendOnce(path, wire => call('/mutate', wire));
    assert.deepEqual(state.pending, []);

    // Closeout: lost batch response, pull boundary inside the closeout, restart, retry.
    for (const action of [queue('c-1', 'pump-17', 'visit', {amount: 1}),
      queue('c-2', 'pump-17', 'patch', {done: true}),
      queue('c-3', 'new-\u00e9', 'create', body({title: 'Urgent \u{1F6A8}'})),
      queue('after', 'pump-17', 'patch', {assignee: null})]) {
      state = reduce(state, action);
    }
    await save(path, state);
    let sentWire;
    await assert.rejects(sendBatchOnce(path, 'closeout-1', 3, async wire => {
      sentWire = wire;
      await call('/batch', wire);
      throw new Error('lost');
    }));
    state = await catchUp(path, call, 'pull', 1);
    assert.deepEqual(mutations(state), ['after']);
    const visible = selectView(state).records.find(r => r.id === 'pump-17').body;
    assert.equal(visible.visits, 11);
    assert.equal(visible.assignee, null);
    state = await sendBatchOnce(path, 'closeout-1', 3, async wire => {
      assert.deepEqual(wire, sentWire);
      return call('/batch', wire);
    });
    assert.equal(state.batch, null);
    assert.deepEqual(mutations(state), ['after']);
    // Fresh re-bootstrap on another tablet converges to the same view.
    const path2 = join(dir, 'desk.json');
    await save(path2, createReplica('north', 'desk'));
    const desk = await catchUp(path2, call, 'snapshot', 1);
    assert.deepEqual(selectView(desk).records, selectView({...state, pending: []}).records);
  } finally {
    proc.kill();
    rmSync(dir, {recursive: true, force: true});
  }
});
