import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createReplica, reduce, selectView} from '../client/replica.mjs';

test('offline creation is visible before first connection', () => {
  const state = reduce(createReplica('north', 'van-7'), {type: 'QUEUE',
    mutation: 'first', id: 'order', kind: 'create',
    data: {title: 'Inspection', assignee: null, visits: 0, done: false}});
  assert.equal(selectView(state).records[0].body.title, 'Inspection');
});
