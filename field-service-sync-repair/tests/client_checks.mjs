import assert from 'node:assert/strict';
import {readFile, readdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const [name, app, directory, url] = process.argv.slice(2);
const {createReplica, reduce, selectView} = await import(pathToFileURL(`${app}/client/replica.mjs`));
const {save, load, sendOnce} = await import(pathToFileURL(`${app}/client/durable.mjs`));
const copy = value => JSON.parse(JSON.stringify(value));
const row = (revision = '1', seq = revision, overrides = {}, id = 'a', deleted = false) => ({
  id, revision, seq, body: {title: 'Inspect pump', assignee: null, visits: 0, done: false, ...overrides},
  deleted,
});
const page = (rows, cut = '1', next = null, epoch = 'e') => ({
  kind: 'snapshot', tenant: 'north', epoch, cut, rows, next_cursor: next,
});
const initial = (rows = [row()], cut = '1') =>
  reduce(createReplica('north', 'van-7'), {type: 'SNAPSHOT', page: page(rows, cut)});
const queue = (state, mutation = 'm1', kind = 'visit', data = {amount: 2}, id = 'a') =>
  reduce(state, {type: 'QUEUE', mutation, kind, data, id});
const ack = (record, mutation = 'm1') => ({
  type: 'ACK', response: {ok: true, tenant: 'north', device: 'van-7', mutation, record},
});
const push = record => ({type: 'PUSH', record, epoch: 'e'});
const view = state => selectView(state).records;
const cases = {};

cases.ack = () => {
  let state = queue(initial());
  state = reduce(state, {type: 'SEND'});
  state = queue(state, 'm2', 'patch', {assignee: 'Mira'});
  const response = ack(row('2', '2', {visits: 2}));
  state = reduce(state, response);
  assert.deepEqual(state.pending.map(p => p.mutation), ['m2']);
  assert.equal(view(state)[0].body.visits, 2);
  assert.equal(view(state)[0].body.assignee, 'Mira');
  assert.equal(state.base.a.body.assignee, null);
  assert.equal(state.checkpoint, '1');
  state = reduce(state, push(row('3', '4', {visits: 2, title: 'Remote dispatch'})));
  state = reduce(state, response);
  assert.equal(view(state)[0].body.title, 'Remote dispatch');
  assert.equal(view(state)[0].body.assignee, 'Mira');
  assert.equal(state.pending.length, 1);
  assert.throws(() => reduce(state, {...response,
    response: {...response.response, device: 'another'}}));
};

cases.precision = () => {
  const source = initial([row('9007199254740992', '9007199254740992')], '9007199254740992');
  const action = push(row('9007199254740993', '9007199254740993', {visits: 1}));
  const beforeState = copy(source), beforeAction = copy(action);
  const changed = reduce(source, action);
  assert.equal(changed.base.a.revision, '9007199254740993');
  assert.equal(changed.base.a.body.visits, 1);
  assert.equal(changed.checkpoint, '9007199254740992');
  assert.deepEqual(source, beforeState);
  assert.deepEqual(action, beforeAction);
  assert.doesNotThrow(() => JSON.stringify(changed));
  assert.throws(() => reduce(changed, push(row('9007199254740993', '9007199254740993',
    {visits: 17}))));
  const pending = queue(changed);
  const beforeView = copy(pending);
  selectView(pending);
  selectView(pending);
  assert.deepEqual(pending, beforeView);
};

cases.snapshot = () => {
  let state = initial([row(), row('1', '2', {}, 'stale')], '2');
  state = queue(state);
  state = queue(state, 'm2', 'patch', {assignee: 'Local'});
  const before = copy(state.base);
  const first = page([row('2', '5')], '10', 'next');
  const last = page([row('1', '6', {}, 'b')], '10');
  state = reduce(state, {type: 'SNAPSHOT', page: first});
  assert.deepEqual(state.base, before);
  assert.equal(state.checkpoint, '2');
  state = reduce(state, {type: 'SNAPSHOT', page: first});
  state = reduce(state, push(row('3', '12', {visits: 1})));
  state = reduce(state, ack(row('4', '13', {visits: 3})));
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: {...last, cut: '11'}}));
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: {...last, epoch: 'other'}}));
  state = reduce(state, {type: 'SNAPSHOT', page: last});
  assert.equal(state.snapshot, null);
  assert.equal(state.checkpoint, '10');
  assert.deepEqual(Object.keys(state.base).sort(), ['a', 'b']);
  assert.equal(state.base.a.revision, '4');
  assert.equal(view(state)[0].body.visits, 3);
  assert.equal(view(state)[0].body.assignee, 'Local');
  const complete = copy(state);
  state = reduce(state, {type: 'SNAPSHOT', page: last});
  state = reduce(state, {type: 'SNAPSHOT', page: first});
  assert.deepEqual(state, complete);
  assert.throws(() => reduce(state, {type: 'SNAPSHOT', page: page([], '9')}));
  state = reduce(state, {type: 'SNAPSHOT', page: page([], '0', null, 'new-epoch')});
  assert.equal(state.epoch, 'new-epoch');
  assert.deepEqual(state.base, {});
  assert.equal(state.pending.length, 1);
};

cases.checkpoint = () => {
  let state = initial();
  state = reduce(state, push(row('3', '5', {visits: 2})));
  assert.equal(state.checkpoint, '1');
  const gap = {kind: 'events', tenant: 'north', epoch: 'e',
    from: '3', after: '5', until: '5', events: [], next_cursor: null};
  assert.throws(() => reduce(state, {type: 'PULL', page: gap}));
  const first = {...gap, from: '1', after: '3',
    events: [row('2', '2', {visits: 1}), row('1', '3', {}, 'b')], next_cursor: 'next'};
  state = reduce(state, {type: 'PULL', page: first});
  assert.equal(state.checkpoint, '3');
  assert.equal(state.base.a.revision, '3');
  assert.ok(state.base.b);
  state = reduce(state, {type: 'PULL', page: first});
  state = reduce(state, {type: 'PULL', page: {...gap, events: [row('3', '5', {visits: 2})]}});
  assert.equal(state.checkpoint, '5');
  assert.throws(() => reduce(state, {...push(row('9', '9')), epoch: 'foreign'}));
};

cases.conflict = () => {
  let state = reduce(queue(initial()), {type: 'SEND'});
  const wire = copy(state.pending[0].wire);
  state = reduce(state, push(row('2', '2', {visits: 1})));
  state = reduce(state, {type: 'SEND'});
  assert.deepEqual(state.pending[0].wire, wire);
  state = reduce(state, {type: 'CONFLICT', mutation: 'm1', current: row('2', '2', {visits: 1})});
  assert.deepEqual(selectView(state).conflicts, ['m1']);
  assert.equal(view(state)[0].body.visits, 1);
  state = reduce(state, {type: 'RESOLVE', mutation: 'm1', mode: 'retry', newMutation: 'retry'});
  state = reduce(state, {type: 'SEND'});
  assert.equal(state.pending[0].wire.base, '2');
  assert.equal(state.pending[0].wire.mutation, 'retry');
  assert.equal(view(state)[0].body.visits, 3);
  assert.throws(() => reduce(state, {type: 'RESOLVE', mutation: 'retry', mode: 'drop'}));
  state = reduce(state, {type: 'CONFLICT', mutation: 'retry', current: null});
  state = reduce(state, {type: 'RESOLVE', mutation: 'retry', mode: 'drop'});
  assert.equal(state.pending.length, 0);
};

cases.tombstone = () => {
  let state = queue(initial(), 'edit', 'patch', {title: 'Offline'});
  state = reduce(state, push(row('2', '3', {}, 'a', true)));
  assert.deepEqual(view(state), []);
  assert.deepEqual(selectView(state).conflicts, ['edit']);
  state = queue(state, 'restore', 'restore', {title: 'Explicit revival'});
  assert.equal(view(state)[0].body.title, 'Explicit revival');
  assert.deepEqual(selectView(state).conflicts, ['edit']);
  assert.equal(state.base.a.deleted, true);
  const missing = queue(initial([], '0'), 'missing', 'visit');
  assert.deepEqual(selectView(missing).conflicts, ['missing']);
};

function permutations(items) {
  if (!items.length) return [[]];
  return items.flatMap((item, i) =>
    permutations(items.filter((_, j) => i !== j)).map(rest => [item, ...rest]));
}

cases.generated = () => {
  for (let amount = 1; amount <= 4; amount++) {
    const confirmed = row('2', '2', {visits: amount});
    const remote = row('3', '4', {visits: amount, title: `Dispatch ${amount}`});
    for (const delivery of permutations([ack(confirmed), push(remote), push(row()), ack(confirmed)])) {
      let state = reduce(queue(initial(), 'm1', 'visit', {amount}), {type: 'SEND'});
      state = queue(state, 'later', 'patch', {done: true});
      for (const action of delivery) state = reduce(state, action);
      assert.deepEqual(state.base.a, remote);
      assert.deepEqual(state.pending.map(p => p.mutation), ['later']);
      assert.equal(state.checkpoint, '1');
      assert.equal(view(state)[0].body.visits, amount);
      assert.equal(view(state)[0].body.done, true);
      assert.equal(view(state)[0].body.title, `Dispatch ${amount}`);
    }
  }
};

cases.atomic = async () => {
  const path = `${directory}/state.json`;
  const first = initial();
  await save(path, first);
  await assert.rejects(save(path, queue(first), phase => {
    assert.equal(phase, 'before_rename');
    throw new Error('crash');
  }), /crash/);
  assert.deepEqual(await load(path), first);
  assert.deepEqual((await readdir(directory)).filter(p => p.endsWith('.tmp')), []);
  await assert.rejects(load(`${directory}/absent.json`));
  await save(path, queue(first));
  assert.equal((await load(path)).pending.length, 1);
};

cases.durable = async () => {
  const path = `${directory}/state.json`;
  await save(path, queue(initial()));
  let sent;
  await assert.rejects(sendOnce(path, async wire => {
    sent = copy(wire);
    assert.deepEqual((await load(path)).pending[0].wire, wire);
    throw new Error('lost response after commit');
  }), /lost response/);
  assert.deepEqual((await load(path)).pending[0].wire, sent);
  await save(path, reduce(await load(path), push(row('3', '4', {visits: 2, title: 'Newer'}))));
  const final = await sendOnce(path, async wire => {
    assert.deepEqual(wire, sent);
    return ack(row('2', '2', {visits: 2})).response;
  });
  assert.equal(final.pending.length, 0);
  assert.equal(final.base.a.revision, '3');
  assert.equal(final.base.a.body.title, 'Newer');
  assert.equal(final.checkpoint, '1');
  await sendOnce(path, () => assert.fail('Empty queue must not exchange'));
};

cases.http = async () => {
  const path = `${directory}/tablet.json`;
  const get = async route => {
    const response = await fetch(url + route);
    assert.equal(response.status, 200);
    return response.json();
  };
  const exchange = async wire => {
    const response = await fetch(url + '/mutate', {method: 'POST',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(wire)});
    assert.equal(response.status, 200, await response.clone().text());
    return response.json();
  };
  let state = reduce(createReplica('north', 'van-7'), {type: 'SNAPSHOT',
    page: await get('/snapshot?tenant=north&limit=2')});
  const id = 'pump-\u6c34';
  state = queue(state, 'create', 'create',
    {title: 'Check caf\u00e9 / \u6c34', assignee: 'Mira', visits: 0, done: false}, id);
  await save(path, state);
  let original;
  await assert.rejects(sendOnce(path, async wire => {
    original = copy(wire);
    await exchange(wire);
    throw new Error('lost after commit');
  }), /lost after commit/);
  state = await sendOnce(path, async wire => {
    assert.deepEqual(wire, original);
    return exchange(wire);
  });
  state = queue(state, 'visit', 'visit', {amount: 2}, id);
  state = queue(state, 'assign', 'patch', {assignee: null, done: true}, id);
  await save(path, state);
  await sendOnce(path, exchange);
  await sendOnce(path, exchange);
  state = await load(path);
  assert.equal(state.checkpoint, '0');
  assert.equal(state.pending.length, 0);
  assert.equal(state.base[id].revision, '3');
  assert.equal(state.base[id].body.visits, 2);
  assert.equal(state.base[id].body.assignee, null);
  let cursor = null;
  const seen = [];
  for (let i = 0; i < 10; i++) {
    const params = new URLSearchParams({tenant: 'north', checkpoint: '0', limit: '1'});
    if (cursor) params.set('cursor', cursor);
    const page = await get('/pull?' + params);
    seen.push(...page.events.map(r => r.seq));
    state = reduce(state, {type: 'PULL', page});
    cursor = page.next_cursor;
    if (cursor === null) break;
  }
  assert.equal(cursor, null);
  assert.deepEqual(seen, ['1', '2', '3']);
  assert.equal(state.checkpoint, '3');
  assert.equal(state.base[id].body.done, true);
  assert.equal(state.base[id].body.title, 'Check caf\u00e9 / \u6c34');
  assert.deepEqual((await get('/snapshot?tenant=north&limit=2')).rows, [state.base[id]]);
  const reused = await fetch(url + '/mutate', {method: 'POST',
    body: JSON.stringify({...original, data: {...original.data, title: 'Changed'}})});
  assert.equal(reused.status, 409);
  assert.equal((await reused.json()).code, 'idempotency_reuse');
};

if (!Object.hasOwn(cases, name)) throw new Error(`Unknown probe ${name}`);
await cases[name]();
console.log(JSON.stringify({ok: true, case: name}));
