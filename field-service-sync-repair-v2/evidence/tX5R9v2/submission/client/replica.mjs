// Headless offline replica. State is plain JSON: every decimal (revision, seq,
// cut, checkpoint) stays a canonical decimal string and is compared via BigInt
// locally, so values beyond 2^53 keep their precision and no BigInt leaks out.

const MAX_SAFE = Number.MAX_SAFE_INTEGER;
const MAX_BATCH = 16;
const KINDS = ['create', 'patch', 'visit', 'delete', 'restore'];
const BODY_FIELDS = ['title', 'assignee', 'visits', 'done'];

const clone = value => JSON.parse(JSON.stringify(value));
const own = (map, key) => Object.hasOwn(map, key) ? map[key] : undefined;
const put = (map, key, value) => Object.defineProperty(map, key, {
  value, enumerable: true, writable: true, configurable: true,
});
const canonical = value => JSON.stringify(value, (_, item) =>
  item && !Array.isArray(item) && typeof item === 'object'
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const nonempty = value => typeof value === 'string' && value.length > 0;
const fail = message => { throw new Error(message); };

function big(value, what = 'decimal') {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) {
    fail(`Invalid ${what}: expected canonical decimal string`);
  }
  return BigInt(value);
}
const cmp = (a, b) => { const x = big(a), y = big(b); return x < y ? -1 : x > y ? 1 : 0; };
const increment = value => (big(value) + 1n).toString();

// Code point order, matching SQLite's BINARY collation of UTF-8 ids on the server.
export function compareIds(a, b) {
  const x = Array.from(a), y = Array.from(b);
  for (let i = 0; i < Math.min(x.length, y.length); i++) {
    const p = x[i].codePointAt(0), q = y[i].codePointAt(0);
    if (p !== q) return p < q ? -1 : 1;
  }
  return x.length - y.length;
}

function validBody(value, partial) {
  if (!isObject(value)) return false;
  const keys = Object.keys(value);
  if (keys.some(key => !BODY_FIELDS.includes(key))) return false;
  if (!partial && keys.length !== BODY_FIELDS.length) return false;
  return keys.every(key => {
    const item = value[key];
    switch (key) {
      case 'title': return nonempty(item);
      case 'assignee': return item === null || typeof item === 'string';
      case 'visits': return Number.isSafeInteger(item) && item >= 0;
      default: return typeof item === 'boolean';
    }
  });
}

function validData(kind, data) {
  if (!isObject(data)) return false;
  switch (kind) {
    case 'create': return validBody(data, false);
    case 'patch': case 'restore': return validBody(data, true);
    case 'visit': return Object.keys(data).length === 1 && Number.isSafeInteger(data.amount)
      && data.amount > 0;
    case 'delete': return Object.keys(data).length === 0;
    default: return false;
  }
}

function checkRecord(record) {
  if (!isObject(record) || !nonempty(record.id) || typeof record.deleted !== 'boolean'
      || !validBody(record.body, false)) {
    fail('Invalid record');
  }
  big(record.revision, 'revision');
  big(record.seq, 'seq');
  return record;
}

// Revision decides; equal revisions must be the same semantic record.
function merge(map, record) {
  checkRecord(record);
  const current = own(map, record.id);
  if (!current) {
    put(map, record.id, clone(record));
    return;
  }
  const order = cmp(record.revision, current.revision);
  if (order > 0) put(map, record.id, clone(record));
  else if (order === 0 && canonical(current) !== canonical(record)) {
    fail('Conflicting records at equal revision');
  }
}

export function createReplica(tenant, device) {
  if (![tenant, device].every(nonempty)) fail('Tenant and device required');
  return {tenant, device, epoch: null, base: {}, pending: [], checkpoint: '0', snapshot: null,
    batch: null};
}

const currentEpoch = state => state.snapshot ? state.snapshot.epoch : state.epoch;

function requireBootstrap(state) {
  if (state.epoch === null && !state.snapshot) fail('Initial snapshot required');
}

// Deliver an authoritative record that is NOT proof of contiguous delivery
// (push, ACK, conflict detail). It never moves the checkpoint.
function receive(state, record, epoch) {
  checkRecord(record);
  if (state.snapshot) {
    if (epoch !== state.snapshot.epoch) fail('Snapshot required for epoch');
    merge(state.snapshot.buffer, record);
    if (state.epoch === epoch) merge(state.base, record);
    return;
  }
  if (state.epoch === null || epoch !== state.epoch) fail('Snapshot required for epoch');
  merge(state.base, record);
}

function batchMembers(state) {
  return state.batch ? state.batch.wire.operations.map(op => op.mutation) : [];
}

function unique(state, mutation) {
  if (!nonempty(mutation) || state.pending.some(p => p.mutation === mutation)
      || batchMembers(state).includes(mutation)) {
    fail('Mutation ID must be unique');
  }
}

function notBatchMember(state, mutation) {
  if (batchMembers(state).includes(mutation)) fail('Intent belongs to an in-flight batch');
}

function checkConfirmations(list) {
  if (list === undefined) return [];
  if (!Array.isArray(list)) fail('Invalid confirmations');
  for (const item of list) {
    if (!isObject(item) || !nonempty(item.device) || !nonempty(item.mutation)
        || !nonempty(item.id)) {
      fail('Invalid confirmation');
    }
    big(item.seq, 'confirmation seq');
  }
  return list;
}

// Retire pending intents that authoritative history proves were committed.
function confirm(state, confirmations) {
  for (const item of confirmations) {
    if (item.device !== state.device) continue;
    const index = state.pending.findIndex(p => p.mutation === item.mutation);
    if (index < 0) continue;
    const intent = state.pending[index];
    if (intent.id !== item.id) fail('Confirmation entity does not match pending intent');
    if (!intent.wire) fail('Confirmation for an unsent intent');
    state.pending.splice(index, 1);
  }
}

const pageSignature = page => canonical({...page, confirmed: page.confirmed ?? []});

function snapshotPage(state, page) {
  if (!isObject(page) || page.kind !== 'snapshot' || page.tenant !== state.tenant
      || !nonempty(page.epoch) || !Array.isArray(page.rows)
      || !(page.next_cursor === null || nonempty(page.next_cursor))) {
    fail('Invalid snapshot');
  }
  big(page.cut, 'cut');
  const confirmed = checkConfirmations(page.confirmed);
  const signature = pageSignature(page);
  if (!state.snapshot) {
    // A re-delivered page of the snapshot that already completed is a no-op.
    if (page.epoch === state.epoch && cmp(page.cut, state.checkpoint) < 0) {
      fail('Backward snapshot');
    }
    if (page.epoch === state.epoch && state.completedPages?.includes(signature)) return;
    state.snapshot = {epoch: page.epoch, cut: page.cut, rows: {}, buffer: {}, confirmed: [],
      pages: []};
  }
  const stage = state.snapshot;
  if (stage.epoch !== page.epoch || stage.cut !== page.cut) fail('Mixed snapshot');
  const ids = new Set();
  for (const row of page.rows) {
    checkRecord(row);
    if (ids.has(row.id)) fail('Duplicate snapshot row');
    ids.add(row.id);
    if (cmp(row.seq, page.cut) > 0) fail('Snapshot row beyond cut');
    const previous = own(stage.rows, row.id);
    if (previous && canonical(previous) !== canonical(row)) fail('Mixed snapshot row');
    put(stage.rows, row.id, clone(row));
  }
  for (const item of confirmed) {
    if (cmp(item.seq, page.cut) > 0) fail('Confirmation beyond cut');
    if (!ids.has(item.id)) fail('Confirmation for an entity outside this page');
    const previous = stage.confirmed.find(c => c.seq === item.seq);
    if (previous && canonical(previous) !== canonical(item)) fail('Mixed snapshot confirmation');
    if (!previous) stage.confirmed.push(clone(item));
  }
  if (!stage.pages.includes(signature)) stage.pages.push(signature);
  if (page.next_cursor !== null) return;

  // Completion: replace base atomically, reconcile, then replay newer deliveries.
  const next = {};
  for (const row of Object.values(stage.rows)) put(next, row.id, row);
  const replay = Object.values(stage.buffer);
  if (state.epoch === stage.epoch) replay.push(...Object.values(state.base));
  for (const row of replay) {
    if (cmp(row.seq, stage.cut) > 0) merge(next, row);
  }
  stage.confirmed.sort((a, b) => cmp(a.seq, b.seq));
  confirm(state, stage.confirmed);
  state.base = next;
  state.epoch = stage.epoch;
  state.checkpoint = stage.cut;
  state.completedPages = stage.pages;
  state.snapshot = null;
}

function pullPage(state, page) {
  if (state.snapshot || state.epoch === null) fail('Invalid pull context');
  if (!isObject(page) || page.kind !== 'events' || page.tenant !== state.tenant
      || page.epoch !== state.epoch || !Array.isArray(page.events)
      || !(page.next_cursor === null || nonempty(page.next_cursor))) {
    fail('Invalid pull context');
  }
  if (cmp(page.from, page.after) > 0 || cmp(page.after, page.until) > 0) {
    fail('Invalid page range');
  }
  const confirmed = checkConfirmations(page.confirmed);
  if (cmp(page.after, state.checkpoint) <= 0) return; // already consumed: idempotent
  if (cmp(page.from, state.checkpoint) !== 0) fail('Noncontiguous pull');
  let previous = page.from;
  for (const row of page.events) {
    checkRecord(row);
    if (cmp(row.seq, previous) <= 0 || cmp(row.seq, page.after) > 0) fail('Event outside page');
    previous = row.seq;
  }
  // A continuation ends at its last event; a final page ends at until.
  if (page.next_cursor !== null
      ? !page.events.length || page.after !== page.events.at(-1).seq
      : page.after !== page.until) {
    fail('Pull page boundary does not match its events');
  }
  // Pages without `confirmed` are the legacy format (treated as empty);
  // otherwise confirmations correspond one-to-one with the returned events.
  if (page.confirmed !== undefined && (confirmed.length !== page.events.length
      || confirmed.some((item, i) => item.seq !== page.events[i].seq
        || item.id !== page.events[i].id))) {
    fail('Confirmations do not match page events');
  }
  for (const row of page.events) merge(state.base, row);
  confirm(state, confirmed);
  state.checkpoint = page.after;
}

function sendBatch(state, action) {
  if (state.epoch === null) fail('Finish bootstrap before send');
  const {batch, count} = action;
  if (!nonempty(batch) || !Number.isInteger(count) || count < 1 || count > MAX_BATCH) {
    fail('Invalid batch request');
  }
  if (state.batch) {
    // The captured envelope is immutable until ACK_BATCH accepts it.
    if (state.batch.wire.batch === batch && state.batch.count === count) return;
    fail('Another batch is in flight');
  }
  if (Object.hasOwn(state.acceptedBatches ?? {}, batch)) fail('Batch ID already acknowledged');
  if (state.pending.length < count) fail('Not enough pending intents for batch');
  const selected = state.pending.slice(0, count);
  if (selected.some(intent => intent.blocked || intent.wire)) {
    fail('Batch members must be unblocked and unsent');
  }
  // Bases come from authoritative base plus earlier selected operations only.
  const predicted = {};
  const operations = selected.map(intent => {
    const base = own(predicted, intent.id) ?? own(state.base, intent.id)?.revision ?? '0';
    put(predicted, intent.id, increment(base));
    const operation = {mutation: intent.mutation, id: intent.id, base, kind: intent.kind,
      data: clone(intent.data)};
    intent.wire = {tenant: state.tenant, device: state.device, ...clone(operation)};
    return operation;
  });
  state.batch = {count, wire: {tenant: state.tenant, device: state.device, batch, operations}};
}

function ackBatch(state, response) {
  requireBootstrap(state);
  // Accepted receipts are remembered per batch ID so delayed duplicates stay idempotent.
  const accepted = state.acceptedBatches ?? {};
  if (isObject(response) && typeof response.batch === 'string'
      && Object.hasOwn(accepted, response.batch)) {
    if (canonical(response) === accepted[response.batch]) return;
    fail('Different receipt for an already acknowledged batch');
  }
  if (!state.batch) fail('No batch in flight');
  const wire = state.batch.wire;
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || response.batch !== wire.batch
      || !Array.isArray(response.responses)
      || response.responses.length !== wire.operations.length) {
    fail('Batch receipt does not match in-flight batch');
  }
  response.responses.forEach((receipt, index) => {
    const op = wire.operations[index];
    if (!isObject(receipt) || receipt.ok !== true || receipt.tenant !== state.tenant
        || receipt.device !== state.device || receipt.mutation !== op.mutation
        || !isObject(receipt.record) || receipt.record.id !== op.id) {
      fail('Batch receipt membership mismatch');
    }
    checkRecord(receipt.record);
  });
  const epoch = currentEpoch(state);
  for (const receipt of response.responses) receive(state, receipt.record, epoch);
  const members = new Set(wire.operations.map(op => op.mutation));
  state.pending = state.pending.filter(p => !members.has(p.mutation));
  state.acceptedBatches = {...accepted};
  put(state.acceptedBatches, wire.batch, canonical(response));
  state.batch = null;
}

export function reduce(input, action) {
  if (!isObject(input) || !Array.isArray(input.pending) || !isObject(input.base)) {
    fail('Invalid state');
  }
  if (!isObject(action) || typeof action.type !== 'string') fail('Invalid action');
  const state = clone(input);
  state.batch ??= null;
  switch (action.type) {
    case 'QUEUE':
      unique(state, action.mutation);
      if (!nonempty(action.id) || !KINDS.includes(action.kind)
          || !validData(action.kind, action.data)) {
        fail('Invalid intent');
      }
      state.pending.push({mutation: action.mutation, id: action.id, kind: action.kind,
        data: clone(action.data), blocked: false});
      break;
    case 'SEND': {
      if (state.epoch === null) fail('Finish bootstrap before send');
      if (state.batch) fail('A batch is in flight');
      const first = state.pending[0];
      // The wire is frozen on first send; repeated SEND returns it unchanged.
      if (first && !first.blocked && !first.wire) {
        first.wire = {tenant: state.tenant, device: state.device, mutation: first.mutation,
          id: first.id, base: own(state.base, first.id)?.revision ?? '0', kind: first.kind,
          data: clone(first.data)};
      }
      break;
    }
    case 'SEND_BATCH':
      sendBatch(state, action);
      break;
    case 'ACK_BATCH':
      ackBatch(state, action.response);
      break;
    case 'ACK': {
      requireBootstrap(state);
      const ack = action.response;
      if (!isObject(ack) || ack.ok !== true || ack.tenant !== state.tenant
          || ack.device !== state.device || !nonempty(ack.mutation)) {
        fail('Foreign or invalid receipt');
      }
      checkRecord(ack.record);
      const index = state.pending.findIndex(p => p.mutation === ack.mutation);
      if (index >= 0) {
        const intent = state.pending[index];
        if (intent.id !== ack.record.id) fail('Receipt entity does not match intent');
        if (!intent.wire) fail('Receipt for an unsent intent');
      }
      receive(state, ack.record, currentEpoch(state));
      if (index >= 0) state.pending.splice(index, 1);
      break;
    }
    case 'CONFLICT': {
      requireBootstrap(state);
      const intent = state.pending.find(p => p.mutation === action.mutation);
      if (!intent) fail('Unknown conflict');
      notBatchMember(state, action.mutation);
      if (action.current !== null && action.current !== undefined) {
        if (!isObject(action.current) || action.current.id !== intent.id) {
          fail('Conflict record does not match intent');
        }
        receive(state, action.current, currentEpoch(state));
      }
      intent.blocked = true;
      break;
    }
    case 'RESOLVE': {
      const index = state.pending.findIndex(p => p.mutation === action.mutation);
      if (index < 0 || !state.pending[index].blocked) fail('Not a blocked intent');
      notBatchMember(state, action.mutation);
      if (action.mode === 'drop') state.pending.splice(index, 1);
      else if (action.mode === 'retry') {
        unique(state, action.newMutation);
        state.pending[index].mutation = action.newMutation;
        state.pending[index].blocked = false;
        delete state.pending[index].wire;
      } else fail('Unknown resolution');
      break;
    }
    case 'PUSH':
      requireBootstrap(state);
      receive(state, action.record, action.epoch);
      break;
    case 'SNAPSHOT':
      snapshotPage(state, action.page);
      break;
    case 'PULL':
      pullPage(state, action.page);
      break;
    default:
      fail(`Unknown action: ${action.type}`);
  }
  return state;
}

export function selectView(state) {
  const projected = clone(state.base);
  const conflicts = [];
  for (const intent of state.pending) {
    let row = own(projected, intent.id);
    // Ordinary edits need a live entity; only restore revives a tombstone.
    let compatible = intent.kind === 'create' ? !row
      : intent.kind === 'restore' ? Boolean(row?.deleted)
        : Boolean(row && !row.deleted);
    if (compatible && intent.kind === 'visit'
        && row.body.visits + intent.data.amount > MAX_SAFE) {
      compatible = false;
    }
    if (intent.blocked || !compatible) {
      conflicts.push(intent.mutation);
      continue;
    }
    if (intent.kind === 'create') {
      row = {id: intent.id, revision: '0', body: clone(intent.data), deleted: false, seq: '0'};
      put(projected, intent.id, row);
    } else if (intent.kind === 'visit') {
      row.body.visits += intent.data.amount;
    } else if (intent.kind === 'delete') {
      row.deleted = true;
    } else {
      Object.assign(row.body, clone(intent.data));
      row.deleted = false;
    }
  }
  return {records: Object.values(projected).filter(row => !row.deleted)
    .sort((a, b) => compareIds(a.id, b.id)), conflicts};
}
