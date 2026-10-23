const clone = value => JSON.parse(JSON.stringify(value));
const own = (map, key) => Object.hasOwn(map, key) ? map[key] : undefined;
const put = (map, key, value) => Object.defineProperty(map, key, {
  value, enumerable: true, writable: true, configurable: true,
});
const canonical = value => JSON.stringify(value, (_, item) =>
  item && !Array.isArray(item) && typeof item === 'object'
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);

const KINDS = ['create', 'patch', 'visit', 'delete', 'restore'];
const BODY_FIELDS = ['title', 'assignee', 'visits', 'done'];
const MAX_VISITS = Number.MAX_SAFE_INTEGER;
const MAX_BATCH = 16;

const fail = message => { throw new Error(message); };
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const isText = value => typeof value === 'string' && value.length > 0;

function decimal(value, what = 'decimal') {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) {
    fail(`Invalid ${what}: expected canonical decimal string`);
  }
  return BigInt(value);
}
const compare = (a, b) => {
  const x = decimal(a), y = decimal(b);
  return x < y ? -1 : x > y ? 1 : 0;
};
const maxDecimal = (a, b) => compare(a, b) >= 0 ? a : b;
const increment = value => (decimal(value) + 1n).toString();

function codePointCompare(a, b) {
  const left = [...a], right = [...b];
  for (let i = 0; i < Math.min(left.length, right.length); i++) {
    const x = left[i].codePointAt(0), y = right[i].codePointAt(0);
    if (x !== y) return x < y ? -1 : 1;
  }
  return left.length - right.length;
}

function validBody(value, partial) {
  if (!isObject(value)) return false;
  const keys = Object.keys(value);
  if (keys.some(key => !BODY_FIELDS.includes(key))) return false;
  if (!partial && keys.length !== BODY_FIELDS.length) return false;
  return keys.every(key => {
    const item = value[key];
    if (key === 'title') return isText(item);
    if (key === 'assignee') return item === null || typeof item === 'string';
    if (key === 'visits') return Number.isSafeInteger(item) && item >= 0;
    return typeof item === 'boolean';
  });
}

function validData(kind, data) {
  if (kind === 'create') return validBody(data, false);
  if (kind === 'patch' || kind === 'restore') return validBody(data, true);
  if (kind === 'visit') {
    return isObject(data) && Object.keys(data).length === 1
      && Number.isSafeInteger(data.amount) && data.amount > 0 && data.amount <= MAX_VISITS;
  }
  return kind === 'delete' && isObject(data) && Object.keys(data).length === 0;
}

function normalizeRecord(record) {
  if (!isObject(record) || !isText(record.id) || typeof record.deleted !== 'boolean'
      || !validBody(record.body, false)) {
    fail('Invalid record');
  }
  decimal(record.revision, 'record revision');
  decimal(record.seq, 'record sequence');
  return {id: record.id, revision: record.revision, body: clone(record.body),
    deleted: record.deleted, seq: record.seq};
}

function normalizeConfirmation(item) {
  if (!isObject(item) || !isText(item.device) || !isText(item.mutation) || !isText(item.id)) {
    fail('Invalid confirmation');
  }
  decimal(item.seq, 'confirmation sequence');
  return {device: item.device, mutation: item.mutation, id: item.id, seq: item.seq};
}

function confirmationsOf(page) {
  if (page.confirmed === undefined) return [];
  if (!Array.isArray(page.confirmed)) fail('Invalid confirmations');
  return page.confirmed.map(normalizeConfirmation);
}

export function createReplica(tenant, device) {
  if (![tenant, device].every(isText)) {
    throw new Error('Tenant and device required');
  }
  return {tenant, device, epoch: null, base: {}, pending: [], checkpoint: '0', snapshot: null};
}

// Merge an authoritative record if it is newer; equal revisions must agree exactly.
function merge(map, input) {
  const record = normalizeRecord(input);
  const current = own(map, record.id);
  if (!current) {
    put(map, record.id, record);
    return;
  }
  const order = compare(record.revision, current.revision);
  if (order > 0) put(map, record.id, record);
  else if (order === 0 && canonical(current) !== canonical(record)) {
    fail('Conflicting records at equal revision');
  }
}

function requireEstablished(state) {
  if (state.epoch === null) fail('Snapshot required before network actions');
}

// Deliver a record received outside the ordered stream (push, receipt, conflict).
// It never advances the checkpoint. While staging, buffer it for post-cut replay.
function receive(state, record, epoch) {
  normalizeRecord(record);
  const stage = state.snapshot;
  let accepted = false;
  if (state.epoch !== null && epoch === state.epoch) {
    merge(state.base, record);
    accepted = true;
  }
  if (stage && epoch === stage.epoch) {
    merge(stage.buffer, record);
    accepted = true;
  }
  if (!accepted) fail('Snapshot required for epoch');
}

// The epoch that a receipt without an explicit epoch belongs to.
function receiptEpoch(state) {
  const epoch = state.snapshot?.epoch ?? state.epoch;
  if (epoch === null) fail('Snapshot required before network actions');
  return epoch;
}

const batchMembers = state => new Set(state.batch?.wire?.operations?.map(op => op.mutation) ?? []);

// Ledger of this replica's mutations proven committed (receipt or confirmation).
// It keeps delayed/duplicate receipts safe and prevents reuse of a confirmed ID.
function retire(state, mutation, id) {
  if (!isObject(state.retired)) state.retired = {};
  put(state.retired, mutation, id);
}
const retiredEntity = (state, mutation) =>
  isObject(state.retired) ? own(state.retired, mutation) : undefined;

function unique(state, mutation) {
  if (!isText(mutation) || state.pending.some(p => p.mutation === mutation)
      || batchMembers(state).has(mutation) || retiredEntity(state, mutation) !== undefined) {
    fail('Mutation ID must be unique');
  }
}

function requireNotInBatch(state, mutation) {
  if (batchMembers(state).has(mutation)) fail('Intent belongs to an in-flight batch');
}

// Retire sent intents that authoritative history proves committed.
function reconcile(state, confirmations) {
  for (const item of confirmations) {
    if (item.device !== state.device) continue;
    const index = state.pending.findIndex(p => p.mutation === item.mutation);
    if (index < 0) continue;
    const intent = state.pending[index];
    if (intent.id !== item.id) fail('Confirmation entity does not match pending intent');
    if (!intent.wire) fail('Confirmation for an unsent intent');
    state.pending.splice(index, 1);
    retire(state, intent.mutation, intent.id);
  }
}

function validateReceipt(state, response) {
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || !isText(response.mutation)) {
    fail('Foreign or invalid receipt');
  }
  normalizeRecord(response.record);
}

function queue(state, action) {
  unique(state, action.mutation);
  if (!isText(action.id) || !KINDS.includes(action.kind) || !validData(action.kind, action.data)) {
    fail('Invalid intent');
  }
  state.pending.push({mutation: action.mutation, id: action.id, kind: action.kind,
    data: clone(action.data), blocked: false});
}

function send(state) {
  if (state.needsSnapshot) fail('Snapshot recovery required before send');
  requireEstablished(state);
  if (state.batch) fail('A batch is in flight');
  const first = state.pending[0];
  if (!first || first.blocked || first.wire) return;
  if (state.snapshot) fail('Finish bootstrap before send');
  first.wire = {tenant: state.tenant, device: state.device, mutation: first.mutation,
    id: first.id, base: own(state.base, first.id)?.revision ?? '0', kind: first.kind,
    data: clone(first.data)};
}

function sendBatch(state, action) {
  if (state.needsSnapshot) fail('Snapshot recovery required before send');
  requireEstablished(state);
  if (!isText(action.batch) || !Number.isInteger(action.count)
      || action.count < 1 || action.count > MAX_BATCH) {
    fail('Invalid batch request');
  }
  if (state.batch) {
    if (state.batch.wire.batch === action.batch && state.batch.count === action.count) return;
    fail('A different batch is in flight');
  }
  if (state.snapshot) fail('Finish bootstrap before send');
  if (state.pending.length < action.count) fail('Not enough pending intents for batch');
  const selected = state.pending.slice(0, action.count);
  if (selected.some(intent => intent.blocked || intent.wire)) {
    fail('Batch cannot include blocked or already sent intents');
  }
  const predicted = {};
  const operations = selected.map(intent => {
    const base = own(predicted, intent.id) ?? own(state.base, intent.id)?.revision ?? '0';
    put(predicted, intent.id, increment(base));
    const operation = {mutation: intent.mutation, id: intent.id, base, kind: intent.kind,
      data: clone(intent.data)};
    intent.wire = {tenant: state.tenant, device: state.device, ...clone(operation)};
    return operation;
  });
  state.batch = {count: action.count,
    wire: {tenant: state.tenant, device: state.device, batch: action.batch, operations}};
}

function ack(state, response) {
  receiptEpoch(state);
  validateReceipt(state, response);
  const index = state.pending.findIndex(p => p.mutation === response.mutation);
  if (index >= 0) {
    const intent = state.pending[index];
    if (intent.id !== response.record.id) fail('Receipt entity does not match pending intent');
    if (!intent.wire) fail('Receipt for an unsent intent');
  } else {
    const known = retiredEntity(state, response.mutation);
    if (known === undefined) fail('Receipt for an unknown mutation');
    if (known !== response.record.id) fail('Receipt entity does not match confirmed mutation');
  }
  receive(state, response.record, receiptEpoch(state));
  if (index >= 0) state.pending.splice(index, 1);
  retire(state, response.mutation, response.record.id);
}

function ackBatch(state, response) {
  receiptEpoch(state);
  if (!state.batch) {
    if (state.lastBatchAck && state.lastBatchAck === canonical(response)) return;
    fail('No batch in flight');
  }
  const wire = state.batch.wire;
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || response.batch !== wire.batch
      || !Array.isArray(response.responses)
      || response.responses.length !== wire.operations.length) {
    fail('Foreign, invalid or incomplete batch receipt');
  }
  response.responses.forEach((receipt, i) => {
    validateReceipt(state, receipt);
    const operation = wire.operations[i];
    if (receipt.mutation !== operation.mutation || receipt.record.id !== operation.id) {
      fail('Batch receipt membership or order mismatch');
    }
  });
  for (const receipt of response.responses) {
    receive(state, receipt.record, receiptEpoch(state));
    retire(state, receipt.mutation, receipt.record.id);
  }
  const acknowledged = new Set(wire.operations.map(op => op.mutation));
  state.pending = state.pending.filter(p => !acknowledged.has(p.mutation));
  state.batch = null;
  state.lastBatchAck = canonical(response);
}

function conflict(state, action) {
  receiptEpoch(state);
  const intent = state.pending.find(p => p.mutation === action.mutation);
  if (!intent) fail('Unknown conflict');
  requireNotInBatch(state, action.mutation);
  if (action.current !== null && action.current !== undefined) {
    if (normalizeRecord(action.current).id !== intent.id) fail('Conflict record for another entity');
    receive(state, action.current, receiptEpoch(state));
  }
  intent.blocked = true;
}

function resolve(state, action) {
  const index = state.pending.findIndex(p => p.mutation === action.mutation);
  if (index < 0 || !state.pending[index].blocked) fail('Not a blocked intent');
  requireNotInBatch(state, action.mutation);
  if (action.mode === 'drop') state.pending.splice(index, 1);
  else if (action.mode === 'retry') {
    unique(state, action.newMutation);
    const intent = state.pending[index];
    intent.mutation = action.newMutation;
    intent.blocked = false;
    delete intent.wire;
  } else fail('Unknown resolution');
}

function recoveryRequired(state, action) {
  if (state.epoch === null || action.epoch !== state.epoch) fail('Recovery for a foreign epoch');
  decimal(action.floor, 'recovery floor');
  state.needsSnapshot = true;
  state.recoveryFloor = state.recoveryFloor != null
    ? maxDecimal(state.recoveryFloor, action.floor) : action.floor;
  state.snapshot = null;
}

function snapshot(state, action) {
  const page = action.page;
  if (!isObject(page) || page.kind !== 'snapshot' || page.tenant !== state.tenant
      || !isText(page.epoch) || !Array.isArray(page.rows)
      || (page.next_cursor !== null && !isText(page.next_cursor))) {
    fail('Invalid snapshot');
  }
  decimal(page.cut, 'snapshot cut');
  const rows = page.rows.map(normalizeRecord);
  const confirmations = confirmationsOf(page);
  for (const row of rows) if (compare(row.seq, page.cut) > 0) fail('Snapshot row beyond cut');
  for (const item of confirmations) {
    if (compare(item.seq, page.cut) > 0) fail('Snapshot confirmation beyond cut');
  }
  const sameEpoch = page.epoch === state.epoch;
  const signature = canonical(page);
  if (!state.snapshot) {
    if (state.needsSnapshot && sameEpoch && compare(page.cut, state.recoveryFloor) < 0) {
      fail('Snapshot cut precedes recovery floor');
    }
    if (sameEpoch && !state.needsSnapshot && state.completedPages?.includes(signature)) return;
    if (sameEpoch && compare(page.cut, state.checkpoint) < 0) fail('Backward snapshot');
    state.snapshot = {epoch: page.epoch, cut: page.cut, rows: {}, confirmed: [], buffer: {},
      pages: []};
  }
  const stage = state.snapshot;
  if (stage.epoch !== page.epoch || stage.cut !== page.cut) fail('Mixed snapshot');
  if (!stage.pages.includes(signature)) {
    for (const row of rows) {
      const previous = own(stage.rows, row.id);
      if (previous && canonical(previous) !== canonical(row)) fail('Mixed snapshot row');
      put(stage.rows, row.id, row);
    }
    const known = new Set(stage.confirmed.map(canonical));
    for (const item of confirmations) {
      if (!known.has(canonical(item))) {
        stage.confirmed.push(item);
        known.add(canonical(item));
      }
    }
    stage.pages.push(signature);
  }
  if (page.next_cursor !== null) return;

  // Atomic completion: new base at the cut, retire confirmed sent work, replay later deliveries.
  const base = {};
  for (const row of Object.values(stage.rows)) put(base, row.id, clone(row));
  const later = Object.values(stage.buffer);
  if (sameEpoch) later.push(...Object.values(state.base));
  for (const row of later) if (compare(row.seq, stage.cut) > 0) merge(base, row);
  const confirmed = [...stage.confirmed].sort((a, b) => compare(a.seq, b.seq));
  reconcile(state, confirmed);
  state.base = base;
  state.epoch = stage.epoch;
  state.checkpoint = stage.cut;
  state.completedPages = stage.pages;
  state.snapshot = null;
  if (state.needsSnapshot !== undefined || state.recoveryFloor !== undefined) {
    state.needsSnapshot = false;
    state.recoveryFloor = null;
  }
}

function pull(state, action) {
  const page = action.page;
  if (state.needsSnapshot) fail('Snapshot recovery required before pull');
  if (!isObject(page) || state.snapshot || state.epoch === null || page.kind !== 'events'
      || page.tenant !== state.tenant || page.epoch !== state.epoch) {
    fail('Invalid pull context');
  }
  if (!Array.isArray(page.events)
      || (page.next_cursor !== undefined && page.next_cursor !== null && !isText(page.next_cursor))) {
    fail('Invalid pull page');
  }
  if (compare(page.from, page.after) > 0 || compare(page.after, page.until) > 0) {
    fail('Invalid page range');
  }
  const events = page.events.map(normalizeRecord);
  const confirmations = confirmationsOf(page);
  if (page.next_cursor === null && compare(page.after, page.until) !== 0) {
    fail('Final pull page must end at until');
  }
  if (isText(page.next_cursor)
      && (!events.length || compare(page.after, events[events.length - 1].seq) !== 0)) {
    fail('Partial pull page must end at its last event');
  }
  if (compare(page.after, state.checkpoint) <= 0) return;
  if (compare(page.from, state.checkpoint) !== 0) fail('Noncontiguous pull');
  let previous = page.from;
  for (const row of events) {
    if (compare(row.seq, previous) <= 0 || compare(row.seq, page.after) > 0) {
      fail('Event outside page or out of order');
    }
    previous = row.seq;
    merge(state.base, row);
  }
  const seqs = new Set(events.map(row => `${row.id}\u0000${row.seq}`));
  for (const item of confirmations) {
    if (!seqs.has(`${item.id}\u0000${item.seq}`)) fail('Confirmation without event');
  }
  reconcile(state, confirmations);
  state.checkpoint = page.after;
}

export function reduce(input, action) {
  if (!isObject(action) || typeof action.type !== 'string') throw new Error('Invalid action');
  const state = clone(input);
  if (!isObject(state) || !Array.isArray(state.pending) || !isObject(state.base)) {
    throw new Error('Invalid replica state');
  }
  switch (action.type) {
    case 'QUEUE': queue(state, action); break;
    case 'SEND': send(state); break;
    case 'SEND_BATCH': sendBatch(state, action); break;
    case 'ACK': ack(state, action.response); break;
    case 'ACK_BATCH': ackBatch(state, action.response); break;
    case 'CONFLICT': conflict(state, action); break;
    case 'RESOLVE': resolve(state, action); break;
    case 'PUSH':
      if (!isObject(action.record)) fail('Invalid push');
      if (state.epoch === null && !state.snapshot) fail('Snapshot required for epoch');
      receive(state, action.record, action.epoch);
      break;
    case 'RECOVERY_REQUIRED': recoveryRequired(state, action); break;
    case 'SNAPSHOT': snapshot(state, action); break;
    case 'PULL': pull(state, action); break;
    default:
      throw new Error(`Unknown action: ${action.type}`);
  }
  return state;
}

function compatible(intent, row) {
  if (intent.kind === 'create') return !row;
  if (intent.kind === 'restore') return Boolean(row) && row.deleted;
  return Boolean(row) && !row.deleted;
}

export function selectView(state) {
  const projected = clone(state.base);
  const conflicts = [];
  for (const intent of state.pending) {
    let row = own(projected, intent.id);
    if (intent.blocked || !compatible(intent, row)) {
      conflicts.push(intent.mutation);
      continue;
    }
    if (intent.kind === 'create') {
      row = {id: intent.id, revision: '0', body: clone(intent.data), deleted: false, seq: '0'};
      put(projected, intent.id, row);
    } else if (intent.kind === 'visit') row.body.visits += intent.data.amount;
    else if (intent.kind === 'delete') row.deleted = true;
    else {
      Object.assign(row.body, clone(intent.data));
      row.deleted = false;
    }
  }
  return {records: Object.values(projected).filter(row => !row.deleted)
    .sort((a, b) => codePointCompare(a.id, b.id)), conflicts};
}
