// Client regressions (imported by tests/client-smoke.mjs).
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, readdir, rm, writeFile} from 'node:fs/promises';
import {createServer} from 'node:net';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createReplica, reduce, selectView} from '../client/replica.mjs';
import {load, save, sendOnce, sendBatchOnce} from '../client/durable.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const EPOCH = 'dispatch-2026-04';
const BIG = '9007199254740993';
const body = (extra = {}) => ({title: 'Inspect', assignee: null, visits: 0, done: false, ...extra});
const rec = (id, revision, seq, extra = {}, deleted = false) =>
  ({id, revision, seq, body: body(extra), deleted});
const snap = (rows, {cut = '10', epoch = EPOCH, next = null, confirmed} = {}) =>
  ({kind: 'snapshot', tenant: 'north', epoch, cut, rows, next_cursor: next,
    ...(confirmed ? {confirmed} : {})});
const pull = (from, after, events, {until = after, confirmed} = {}) =>
  ({kind: 'events', tenant: 'north', epoch: EPOCH, from, after, until, events,
    next_cursor: null, ...(confirmed ? {confirmed} : {})});
const ack = (mutation, record, device = 'van-7') =>
  ({ok: true, tenant: 'north', device, mutation, record});
const run = (state, ...actions) => actions.reduce(reduce, state);
const boot = (rows = [rec('pump', '1', '5')], cut = '10') =>
  reduce(createReplica('north', 'van-7'), {type: 'SNAPSHOT', page: snap(rows, {cut})});
const queue = (mutation, id, kind, data) => ({type: 'QUEUE', mutation, id, kind, data});
const ids = state => state.pending.map(p => p.mutation);

test('incident trace: delayed ACK keeps later edit and checkpoint', async () => {
  const input = JSON.parse(await readFile(join(ROOT, 'incidents/client-actions.json'), 'utf8'));
  let state = createReplica(input.tenant, input.device);
  for (const action of input.actions) state = reduce(state, action);
  const view = selectView(state).records[0].body;
  assert.equal(view.visits, input.expected_visible.visits);
  assert.equal(view.assignee, input.expected_visible.assignee);
  assert.deepEqual(ids(state), input.expected_pending);
  assert.equal(state.checkpoint, input.expected_checkpoint);
});

test('reducer is pure and JSON-only', () => {
  const state = boot();
  const frozen = JSON.stringify(state);
  const action = queue('m', 'pump', 'visit', {amount: 1});
  const next = reduce(state, action);
  assert.equal(JSON.stringify(state), frozen);
  next.pending[0].data.amount = 5;
  assert.equal(action.data.amount, 1);
  assert.doesNotThrow(() => JSON.stringify(reduce(next, {type: 'SEND'})));
});

test('decimal strings compare beyond 2^53', () => {
  let state = boot([rec('pump', '9007199254740992', '9007199254740992')], BIG);
  state = reduce(state, {type: 'PUSH', epoch: EPOCH,
    record: rec('pump', BIG, '9007199254740994', {visits: 1})});
  assert.equal(state.base.pump.revision, BIG);
  assert.equal(selectView(state).records[0].body.visits, 1);
  // An older revision that collapses to the same Number must not overwrite.
  state = reduce(state, {type: 'PUSH', epoch: EPOCH,
    record: rec('pump', '9007199254740992', '9007199254740992')});
  assert.equal(state.base.pump.revision, BIG);
  assert.throws(() => reduce(state, {type: 'PUSH', epoch: EPOCH,
    record: rec('pump', BIG, '9007199254740995', {visits: 7})}), /equal revision/);
  assert.equal(state.checkpoint, BIG);
});

test('PUSH and ACK never advance checkpoint; pull must be contiguous', () => {
  let state = boot();
  state = run(state, {type: 'PUSH', epoch: EPOCH, record: rec('valve', '1', '15')});
  assert.equal(state.checkpoint, '10');
  assert.throws(() => reduce(state, {type: 'PULL', page: pull('15', '20', [])}), /Noncontiguous/);
  assert.throws(() => reduce(state, {type: 'PUSH', epoch: 'other', record: rec('x', '1', '1')}),
    /Snapshot required/);
  state = reduce(state, {type: 'PULL', page: pull('10', '20', [rec('gate', '1', '12'),
    rec('valve', '1', '15')])});
  assert.equal(state.checkpoint, '20');
  assert.deepEqual(selectView(state).records.map(r => r.id), ['gate', 'pump', 'valve']);
  // Already-consumed page is idempotent.
  assert.deepEqual(reduce(state, {type: 'PULL', page: pull('10', '20', [])}), state);
  assert.throws(() => reduce(state, {type: 'PULL', page: pull('20', '25', [rec('z', '1', '26')])}),
    /outside page/);
});

test('network actions require a snapshot; QUEUE does not', () => {
  const fresh = reduce(createReplica('north', 'van-7'), queue('a', 'w', 'create', body()));
  assert.throws(() => reduce(fresh, {type: 'SEND'}));
  assert.throws(() => reduce(fresh, {type: 'PUSH', epoch: EPOCH, record: rec('w', '1', '1')}));
  assert.throws(() => reduce(fresh, {type: 'PULL', page: pull('0', '1', [])}));
  assert.throws(() => reduce(fresh, queue('a', 'w', 'create', body())), /unique/);
  assert.throws(() => reduce(fresh, queue('b', 'w', 'visit', {amount: true})));
  assert.throws(() => reduce(fresh, {type: 'BOGUS'}));
});

test('snapshot staging is atomic, removes stale rows and replays post-cut deliveries', () => {
  let state = boot([rec('old', '1', '3'), rec('pump', '1', '5')]);
  state = reduce(state, queue('local', 'pump', 'patch', {assignee: 'Ann'}));
  state = reduce(state, {type: 'SNAPSHOT', page: snap([rec('a', '1', '2')],
    {cut: '20', next: 'c1'})});
  assert.ok(state.snapshot);
  assert.equal(state.checkpoint, '10');
  assert.deepEqual(Object.keys(state.base).sort(), ['old', 'pump']);
  assert.throws(() => reduce(state, {type: 'PULL', page: pull('10', '11', [])}));
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snap([], {cut: '21'})}), /Mixed/);
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '3', '25', {done: true})});
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '2', '18')});
  // Retried identical page is fine; a conflicting duplicate row is not.
  state = reduce(state, {type: 'SNAPSHOT', page: snap([rec('a', '1', '2')], {cut: '20', next: 'c1'})});
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snap([rec('a', '1', '2', {done: true})],
    {cut: '20', next: 'c1'})}), /Mixed snapshot row/);
  state = reduce(state, {type: 'SNAPSHOT', page: snap([rec('pump', '2', '18')], {cut: '20'})});
  assert.equal(state.snapshot, null);
  assert.equal(state.checkpoint, '20');
  assert.deepEqual(Object.keys(state.base).sort(), ['a', 'pump']);
  assert.equal(state.base.pump.revision, '3');
  assert.deepEqual(ids(state), ['local']);
  assert.equal(selectView(state).records.find(r => r.id === 'pump').body.assignee, 'Ann');
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: snap([], {cut: '19'})}), /Backward/);
  // Duplicate final page of the completed snapshot is idempotent.
  assert.deepEqual(reduce(state, {type: 'SNAPSHOT',
    page: snap([rec('pump', '2', '18')], {cut: '20'})}), state);
});

test('new epoch requires a new snapshot and replaces history', () => {
  let state = boot([rec('pump', '7', '5')]);
  state = reduce(state, {type: 'SNAPSHOT', page: snap([rec('pump', '1', '1')],
    {epoch: 'epoch-2', cut: '1'})});
  assert.equal(state.epoch, 'epoch-2');
  assert.equal(state.base.pump.revision, '1');
  assert.equal(state.checkpoint, '1');
});

test('ACK removes only its intent; duplicates and delayed ACKs are harmless', () => {
  let state = boot();
  state = run(state, queue('v', 'pump', 'visit', {amount: 1}), {type: 'SEND'},
    queue('p', 'pump', 'patch', {assignee: 'Mira'}), queue('q', 'other', 'create', body()));
  const wire = state.pending[0].wire;
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '5', '30')});
  assert.deepEqual(reduce(state, {type: 'SEND'}).pending[0].wire, wire);
  assert.equal(wire.base, '1');
  const receipt = ack('v', rec('pump', '2', '11', {visits: 1}));
  state = reduce(state, {type: 'ACK', response: receipt});
  assert.deepEqual(ids(state), ['p', 'q']);
  assert.equal(state.base.pump.revision, '5');
  state = reduce(state, {type: 'ACK', response: receipt});
  assert.deepEqual(ids(state), ['p', 'q']);
  assert.throws(() => reduce(state, {type: 'ACK', response: ack('v', rec('pump', '2', '11'),
    'van-8')}), /Foreign/);
  assert.throws(() => reduce(state, {type: 'ACK', response: ack('p', rec('pump', '6', '31'))}),
    /unsent/);
});

test('visit is not doubled after ACK', () => {
  let state = boot([rec('pump', '1', '5', {visits: 3})]);
  state = run(state, queue('v', 'pump', 'visit', {amount: 1}), {type: 'SEND'});
  assert.equal(selectView(state).records[0].body.visits, 4);
  state = reduce(state, {type: 'ACK', response: ack('v', rec('pump', '2', '11', {visits: 4}))});
  assert.equal(selectView(state).records[0].body.visits, 4);
});

test('conflict blocks, resolve retries with new base or drops', () => {
  let state = boot();
  state = run(state, queue('a', 'pump', 'patch', {done: true}), queue('b', 'pump', 'visit',
    {amount: 1}), {type: 'SEND'});
  assert.throws(() => reduce(state, {type: 'CONFLICT', mutation: 'b', current: null}), /unsent/);
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'a', mode: 'drop'}));
  const current = rec('pump', '4', '12', {assignee: 'Zed'});
  state = reduce(state, {type: 'CONFLICT', mutation: 'a', current});
  assert.equal(state.pending[0].wire.base, '1');
  assert.deepEqual(selectView(state).conflicts, ['a']);
  assert.equal(reduce(state, {type: 'SEND'}).pending[0].wire.base, '1');
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'a', mode: 'retry',
    newMutation: 'b'}), /unique/);
  const retried = run(state, {type: 'RESOLVE', mutation: 'a', mode: 'retry', newMutation: 'a2'},
    {type: 'SEND'});
  assert.deepEqual(ids(retried), ['a2', 'b']);
  assert.equal(retried.pending[0].wire.base, '4');
  assert.equal(retried.pending[0].wire.mutation, 'a2');
  assert.deepEqual(ids(reduce(state, {type: 'RESOLVE', mutation: 'a', mode: 'drop'})), ['b']);
});

test('edits cannot revive deleted or missing entities; restore can', () => {
  let state = boot([rec('pump', '2', '5', {}, true)]);
  state = run(state, queue('p', 'pump', 'patch', {done: true}), queue('r', 'pump', 'restore',
    {assignee: 'Ann'}), queue('v', 'pump', 'visit', {amount: 2}), queue('m', 'ghost', 'visit',
    {amount: 1}), queue('c', 'new', 'create', body({title: 'Ünïcode ✓'})));
  const view = selectView(state);
  assert.deepEqual(view.conflicts, ['p', 'm']);
  assert.deepEqual(view.records.map(r => [r.id, r.body.visits, r.body.assignee]),
    [['new', 0, null], ['pump', 2, 'Ann']]);
  assert.equal(state.base.pump.deleted, true);
});

test('pull confirmations retire sent intents, reject unsent or mismatched ones', () => {
  let state = boot([rec('pump', '1', '5', {visits: 1})]);
  state = run(state, queue('v', 'pump', 'visit', {amount: 1}), {type: 'SEND'},
    queue('later', 'pump', 'patch', {assignee: 'Ann'}));
  const page = pull('10', '20', [rec('pump', '2', '12', {visits: 2}),
    rec('pump', '3', '14', {visits: 2, done: true})], {confirmed: [
    {device: 'van-7', mutation: 'v', id: 'pump', seq: '12'},
    {device: 'van-9', mutation: 'later', id: 'pump', seq: '14'}]});
  const next = reduce(state, {type: 'PULL', page});
  assert.deepEqual(ids(next), ['later']);
  assert.equal(next.checkpoint, '20');
  const view = selectView(next).records[0].body;
  assert.deepEqual([view.visits, view.done, view.assignee], [2, true, 'Ann']);
  // Consumed duplicate does not act on new local work.
  const again = reduce(run(next, {type: 'SEND'}), {type: 'PULL', page});
  assert.deepEqual(ids(again), ['later']);
  const unsent = pull('10', '20', [rec('pump', '2', '12', {visits: 2})], {confirmed: [
    {device: 'van-7', mutation: 'later', id: 'pump', seq: '12'}]});
  assert.throws(() => reduce(state, {type: 'PULL', page: unsent}), /unsent/);
  const wrongEntity = pull('10', '20', [rec('valve', '1', '12')], {confirmed: [
    {device: 'van-7', mutation: 'v', id: 'valve', seq: '12'}]});
  assert.throws(() => reduce(state, {type: 'PULL', page: wrongEntity}), /mismatch/);
  // Older pages without confirmed are accepted.
  assert.equal(reduce(state, {type: 'PULL', page: pull('10', '11', [])}).checkpoint, '11');
});

test('rebootstrap after lost response: historical confirmation prevents double visit', () => {
  let state = boot([rec('pump', '1', '5', {visits: 1})]);
  state = run(state, queue('v', 'pump', 'visit', {amount: 1}), {type: 'SEND'},
    queue('note', 'pump', 'patch', {assignee: 'Lee'}));
  const confirmed = [{device: 'van-7', mutation: 'v', id: 'pump', seq: '12'},
    {device: 'other', mutation: 'x', id: 'pump', seq: '15'}];
  state = reduce(state, {type: 'SNAPSHOT', page: snap([rec('a', '1', '2')],
    {cut: '30', next: 'p2', confirmed: []})});
  assert.deepEqual(ids(state), ['v', 'note']);
  state = reduce(state, {type: 'SNAPSHOT', page: snap([rec('pump', '3', '15',
    {visits: 2, done: true})], {cut: '30', confirmed})});
  assert.deepEqual(ids(state), ['note']);
  const pump = selectView(state).records.find(r => r.id === 'pump').body;
  assert.deepEqual([pump.visits, pump.assignee], [2, 'Lee']);
  // A delayed ACK after confirmation is safe.
  const after = reduce(state, {type: 'ACK', response: ack('v', rec('pump', '2', '12',
    {visits: 2}))});
  assert.deepEqual(ids(after), ['note']);
  assert.equal(after.base.pump.revision, '3');
});

test('batch send freezes predicted bases and survives partial confirmation', () => {
  let state = boot([rec('pump', '7', '5'), rec('valve', '3', '6')]);
  state = run(state, queue('v', 'pump', 'visit', {amount: 1}),
    queue('d', 'pump', 'patch', {done: true}), queue('vd', 'valve', 'patch', {done: true}),
    queue('n', 'new', 'create', body()), queue('later', 'valve', 'patch', {assignee: 'Kim'}));
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'b', count: 6}));
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'b', count: 17}));
  state = reduce(state, {type: 'SEND_BATCH', batch: 'close-3', count: 4});
  const wire = state.batch.wire;
  assert.deepEqual(wire.operations.map(op => [op.mutation, op.id, op.base]),
    [['v', 'pump', '7'], ['d', 'pump', '8'], ['vd', 'valve', '3'], ['n', 'new', '0']]);
  assert.equal(state.pending[1].wire.base, '8');
  assert.equal(state.pending[4].wire, undefined);
  assert.throws(() => reduce(state, {type: 'SEND'}), /Batch in flight/);
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'other', count: 4}));
  assert.throws(() => reduce(state, {type: 'CONFLICT', mutation: 'd', current: null}),
    /in-flight batch/);
  assert.throws(() => reduce(state, queue('v', 'x', 'delete', {})), /unique/);
  state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '10', '40')});
  // Pull page boundary inside the committed closeout retires only the first op.
  state = reduce(state, {type: 'PULL', page: pull('10', '31', [rec('pump', '8', '31',
    {visits: 1})], {until: '40', confirmed: [{device: 'van-7', mutation: 'v', id: 'pump',
    seq: '31'}]})});
  assert.deepEqual(ids(state), ['d', 'vd', 'n', 'later']);
  assert.deepEqual(reduce(state, {type: 'SEND_BATCH', batch: 'close-3', count: 4}).batch.wire, wire);
  const responses = wire.operations.map((op, index) => ack(op.mutation,
    rec(op.id, String(BigInt(op.base) + 1n), String(31 + index), op.id === 'pump'
      ? {visits: 1, done: index === 1} : op.id === 'valve' ? {done: true} : {})));
  const response = {ok: true, tenant: 'north', device: 'van-7', batch: 'close-3', responses};
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response,
    responses: responses.slice(1)}}), /match/);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response,
    responses: [responses[1], responses[0], ...responses.slice(2)]}}), /mismatch/);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response, ok: false}}));
  state = reduce(state, {type: 'ACK_BATCH', response});
  assert.equal(state.batch, null);
  assert.deepEqual(ids(state), ['later']);
  assert.equal(state.base.pump.revision, '10');
  assert.equal(state.base.valve.revision, '4');
  assert.deepEqual(reduce(state, {type: 'ACK_BATCH', response}), state);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...response, batch: 'z'}}));
  assert.equal(selectView(state).records.find(r => r.id === 'valve').body.assignee, 'Kim');
});

test('optimistic visit beyond 2^53-1 is a conflict, not an imprecise total', () => {
  let state = boot([rec('pump', '1', '5', {visits: 9007199254740990})]);
  state = run(state, queue('a', 'pump', 'visit', {amount: 1}), queue('b', 'pump', 'visit',
    {amount: 1}));
  const view = selectView(state);
  assert.deepEqual(view.conflicts, ['b']);
  assert.equal(view.records[0].body.visits, 9007199254740991);
});

test('duplicate ACK_BATCH stays idempotent after later batches', () => {
  let state = boot([rec('pump', '1', '5')]);
  const accept = (s, name, mutation, revision, seq) => {
    s = run(s, queue(mutation, 'pump', 'visit', {amount: 1}),
      {type: 'SEND_BATCH', batch: name, count: 1});
    const response = {ok: true, tenant: 'north', device: 'van-7', batch: name,
      responses: [ack(mutation, rec('pump', revision, seq))]};
    return [reduce(s, {type: 'ACK_BATCH', response}), response];
  };
  let first, second;
  [state, first] = accept(state, 'b1', 'm1', '2', '11');
  [state, second] = accept(state, 'b2', 'm2', '3', '12');
  assert.deepEqual(reduce(state, {type: 'ACK_BATCH', response: first}), state);
  assert.deepEqual(reduce(state, {type: 'ACK_BATCH', response: second}), state);
  assert.throws(() => reduce(state, {type: 'ACK_BATCH', response: {...first,
    responses: [ack('m1', rec('pump', '2', '99'))]}}));
});

test('batch members must be unsent and unblocked', () => {
  let state = boot();
  state = run(state, queue('a', 'pump', 'visit', {amount: 1}), {type: 'SEND'},
    queue('b', 'pump', 'visit', {amount: 1}));
  assert.throws(() => reduce(state, {type: 'SEND_BATCH', batch: 'x', count: 2}), /unsent/);
});

test('trace runner reports malformed actions on stderr with nonzero exit', async () => {
  const result = await new Promise(resolve => {
    const child = spawn(process.execPath, [join(ROOT, 'client/trace.mjs')]);
    let stderr = '';
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('close', code => resolve({code, stderr}));
    child.stdin.end(JSON.stringify({actions: [{type: 'SEND'}]}));
  });
  assert.notEqual(result.code, 0);
  assert.match(result.stderr, /Snapshot required/);
});

test('durable save is atomic and load of a missing file fails', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'replica-'));
  try {
    const path = join(dir, 'state.json');
    await assert.rejects(load(path));
    await save(path, boot());
    const before = await readFile(path, 'utf8');
    await assert.rejects(save(path, createReplica('north', 'x'), async stage => {
      if (stage === 'before_rename') throw new Error('crash');
    }), /crash/);
    assert.equal(await readFile(path, 'utf8'), before);
    assert.deepEqual(await readdir(dir), ['state.json']);
  } finally {
    await rm(dir, {recursive: true, force: true});
  }
});

test('sendOnce persists wire before exchange and retries identically after restart', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'replica-'));
  try {
    const path = join(dir, 'state.json');
    await save(path, run(boot(), queue('v', 'pump', 'visit', {amount: 1}),
      queue('p', 'pump', 'patch', {assignee: 'Ann'})));
    const seen = [];
    await assert.rejects(sendOnce(path, async wire => {
      seen.push(wire);
      assert.deepEqual((await load(path)).pending[0].wire, wire);
      throw new Error('response lost');
    }), /response lost/);
    let state = await load(path);
    assert.deepEqual(ids(state), ['v', 'p']);
    state = reduce(state, {type: 'PUSH', epoch: EPOCH, record: rec('pump', '3', '20')});
    await save(path, state);
    state = await sendOnce(path, async wire => {
      seen.push(wire);
      return ack('v', rec('pump', '2', '11', {visits: 1}));
    });
    assert.deepEqual(seen[1], seen[0]);
    assert.deepEqual(ids(state), ['p']);
    assert.deepEqual(await load(path), state);
    const blocked = reduce(run(state, {type: 'SEND'}), {type: 'CONFLICT', mutation: 'p',
      current: null});
    await save(path, blocked);
    let called = false;
    assert.deepEqual(await sendOnce(path, async () => { called = true; }), blocked);
    assert.equal(called, false);
  } finally {
    await rm(dir, {recursive: true, force: true});
  }
});

test('sendBatchOnce retries the stored full batch after partial confirmation', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'replica-'));
  try {
    const path = join(dir, 'state.json');
    await save(path, run(boot(), queue('v', 'pump', 'visit', {amount: 1}),
      queue('d', 'pump', 'patch', {done: true}), queue('x', 'pump', 'patch', {assignee: 'Q'})));
    const seen = [];
    await assert.rejects(sendBatchOnce(path, 'b', 2, async wire => {
      seen.push(wire);
      throw new Error('lost');
    }));
    let state = reduce(await load(path), {type: 'PULL', page: pull('10', '12', [
      rec('pump', '2', '11', {visits: 1}), rec('pump', '3', '12', {visits: 1, done: true})],
    {confirmed: [{device: 'van-7', mutation: 'v', id: 'pump', seq: '11'},
      {device: 'van-7', mutation: 'd', id: 'pump', seq: '12'}]})});
    assert.deepEqual(ids(state), ['x']);
    await save(path, state);
    await assert.rejects(sendOnce(path, async () => assert.fail('must not send')), /Batch/);
    state = await sendBatchOnce(path, 'b', 2, async wire => {
      seen.push(wire);
      return {ok: true, tenant: 'north', device: 'van-7', batch: 'b', responses: [
        ack('v', rec('pump', '2', '11', {visits: 1})),
        ack('d', rec('pump', '3', '12', {visits: 1, done: true}))]};
    });
    assert.deepEqual(seen[1], seen[0]);
    assert.equal(seen[0].operations.length, 2);
    assert.deepEqual(ids(state), ['x']);
    assert.equal(state.batch, null);
  } finally {
    await rm(dir, {recursive: true, force: true});
  }
});

async function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const {port} = server.address();
      server.close(() => resolve(port));
    });
  });
}

test('end to end: lost response, restart and catch-up against the real server', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'e2e-'));
  const port = await freePort();
  const server = spawn('python3', ['-m', 'server.http', '--db', join(dir, 'db.sqlite'),
    '--port', String(port)], {cwd: ROOT, stdio: 'ignore'});
  const base = `http://127.0.0.1:${port}`;
  const call = async (path, payload) => {
    const response = await fetch(base + path, payload === undefined ? {} : {
      method: 'POST', body: JSON.stringify(payload)});
    return response.json();
  };
  try {
    for (let i = 0; ; i += 1) {
      try { await fetch(`${base}/health`); break; } catch (error) {
        if (i > 100) throw error;
        await new Promise(resolve => setTimeout(resolve, 50));
      }
    }
    await call('/mutate', {tenant: 'north', device: 'desk', mutation: 'seed', id: 'pump',
      base: '0', kind: 'create', data: body()});
    const path = join(dir, 'replica.json');
    let state = createReplica('north', 'van-7');
    state = reduce(state, {type: 'SNAPSHOT', page: await call('/snapshot?tenant=north&limit=5')});
    state = run(state, queue('v', 'pump', 'visit', {amount: 1}),
      queue('a', 'pump', 'patch', {assignee: 'Mira'}));
    await save(path, state);
    // Server commits, response lost.
    await assert.rejects(sendOnce(path, async wire => {
      await call('/mutate', wire);
      throw new Error('lost');
    }));
    // Another device moves the record on.
    await call('/mutate', {tenant: 'north', device: 'desk', mutation: 'done', id: 'pump',
      base: '2', kind: 'patch', data: {done: true}});
    // Restart: catch-up confirms the visit, so it is not doubled.
    state = await load(path);
    const page = await call(`/pull?tenant=north&checkpoint=${state.checkpoint}&limit=1`);
    state = reduce(state, {type: 'PULL', page});
    const rest = await call(`/pull?tenant=north&checkpoint=${page.from}&limit=1&cursor=${
      encodeURIComponent(page.next_cursor)}`);
    state = reduce(state, {type: 'PULL', page: rest});
    assert.deepEqual(ids(state), ['a']);
    assert.equal(selectView(state).records[0].body.visits, 1);
    await save(path, state);
    state = await sendOnce(path, wire => call('/mutate', wire));
    assert.deepEqual(ids(state), []);
    assert.deepEqual(selectView(state).records[0].body,
      {title: 'Inspect', assignee: 'Mira', visits: 1, done: true});
    // A retry of the original lost request still returns the original receipt.
    const again = await call('/mutate', {tenant: 'north', device: 'van-7', mutation: 'v',
      id: 'pump', base: '1', kind: 'visit', data: {amount: 1}});
    assert.equal(again.record.revision, '2');
  } finally {
    server.kill();
    await rm(dir, {recursive: true, force: true});
  }
});
