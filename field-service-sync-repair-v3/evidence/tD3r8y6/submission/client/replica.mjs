// Headless offline replica for the work-order sync protocol (PROTOCOL.md).
// The reducer is pure: it clones its input, never mutates arguments, and keeps
// all sequence/revision values as canonical decimal strings (no BigInt leaks).

const clone = value => (value === undefined ? undefined : JSON.parse(JSON.stringify(value)));
const own = (map, key) => (Object.hasOwn(map, key) ? map[key] : undefined);
const put = (map, key, value) => Object.defineProperty(map, key, {
  value, enumerable: true, writable: true, configurable: true,
});
const canonical = value => JSON.stringify(value, (_, item) =>
  item && !Array.isArray(item) && typeof item === 'object'
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const isText = value => typeof value === 'string' && value.length > 0;
const KINDS = ['create', 'patch', 'visit', 'delete', 'restore'];
const BODY_FIELDS = ['title', 'assignee', 'visits', 'done'];
const MAX_BATCH = 16;

function fail(message) {
  throw new Error(message);
}

function decimal(value, what = 'decimal') {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) {
    fail(`Invalid ${what}: expected canonical decimal string`);
  }
  return value;
}

// Compare canonical decimal strings without losing precision.
function cmp(a, b) {
  decimal(a);
  decimal(b);
  if (a.length !== b.length) return a.length < b.length ? -1 : 1;
  return a < b ? -1 : a > b ? 1 : 0;
}

const increment = value => (BigInt(decimal(value)) + 1n).toString();
const maxDecimal = (a, b) => (cmp(a, b) >= 0 ? a : b);

function validBody(value, partial) {
  if (!isObject(value)) return false;
  const keys = Object.keys(value);
  if (keys.some(key => !BODY_FIELDS.includes(key))) return false;
  if (!partial && keys.length !== BODY_FIELDS.length) return false;
  return keys.every(key => {
    const item = value[key];
    switch (key) {
      case 'title': return isText(item);
      case 'assignee': return item === null || typeof item === 'string';
      case 'visits': return Number.isSafeInteger(item) && item >= 0;
      default: return typeof item === 'boolean';
    }
  });
}

function validIntentData(kind, data) {
  switch (kind) {
    case 'create': return validBody(data, false);
    case 'patch':
    case 'restore': return validBody(data, true);
    case 'visit':
      return isObject(data) && Object.keys(data).length === 1
        && Number.isSafeInteger(data.amount) && data.amount > 0;
    case 'delete': return isObject(data) && Object.keys(data).length === 0;
    default: return false;
  }
}

// Normalize a wire record to its five semantic members.
function normal(record) {
  if (!isObject(record) || !isText(record.id) || typeof record.deleted !== 'boolean'
      || !validBody(record.body, false)) {
    fail('Invalid record');
  }
  return {id: record.id, revision: decimal(record.revision, 'revision'),
    body: clone(record.body), deleted: record.deleted, seq: decimal(record.seq, 'seq')};
}

// Keep the record with the greater revision; equal revisions must agree.
function merge(map, input) {
  const record = normal(input);
  const current = own(map, record.id);
  if (!current) {
    put(map, record.id, record);
    return;
  }
  const order = cmp(record.revision, current.revision);
  if (order > 0) put(map, record.id, record);
  else if (order === 0 && canonical(normal(current)) !== canonical(record)) {
    fail(`Conflicting records at equal revision for ${record.id}`);
  }
}

function normalConfirmation(item) {
  if (!isObject(item) || !isText(item.device) || !isText(item.mutation) || !isText(item.id)) {
    fail('Invalid confirmation');
  }
  return {device: item.device, mutation: item.mutation, id: item.id,
    seq: decimal(item.seq, 'confirmation seq')};
}

// Older pages without `confirmed` are treated as an empty list.
function confirmations(page) {
  if (page.confirmed === undefined) return [];
  if (!Array.isArray(page.confirmed)) fail('Invalid confirmation list');
  return page.confirmed.map(normalConfirmation);
}

const inflight = state => (state.batch && state.batch.wire ? state.batch : null);
const batchOperation = (state, mutation) =>
  inflight(state)?.wire.operations.find(op => op.mutation === mutation);

function requireNetwork(state) {
  if (state.epoch === null && !state.snapshot) fail('Snapshot required before network actions');
}

// Responses to requests sent under the established epoch cannot be attributed
// to a different epoch being bootstrapped; refuse to mix those histories.
function requireReceiptEpoch(state) {
  if (state.snapshot && state.epoch !== null && state.snapshot.epoch !== state.epoch) {
    fail('Receipt epoch is ambiguous while bootstrapping a new epoch');
  }
}

// Deliver an authoritative record from PUSH/ACK/CONFLICT. Never moves checkpoint.
function deliver(state, input) {
  requireNetwork(state);
  const record = normal(input);
  if (state.snapshot) {
    merge(state.snapshot.buffer, record);
    if (state.snapshot.epoch === state.epoch) merge(state.base, record);
  } else {
    merge(state.base, record);
  }
}

// Retire this replica's committed intents named by authoritative confirmations.
function reconcile(state, list) {
  for (const item of list) {
    if (item.device !== state.device) continue;
    const operation = batchOperation(state, item.mutation);
    if (operation && operation.id !== item.id) {
      fail(`Confirmation ${item.mutation} names a different entity`);
    }
    const index = state.pending.findIndex(p => p.mutation === item.mutation);
    if (index < 0) continue;
    const intent = state.pending[index];
    if (intent.id !== item.id) fail(`Confirmation ${item.mutation} names a different entity`);
    if (!intent.wire) fail(`Confirmation ${item.mutation} matches an unsent intent`);
    state.pending.splice(index, 1);
  }
}

function unique(state, mutation) {
  if (!isText(mutation)) fail('Mutation ID required');
  if (state.pending.some(p => p.mutation === mutation) || batchOperation(state, mutation)) {
    fail('Mutation ID must be unique');
  }
}

function requireSendable(state) {
  if (state.epoch === null || state.snapshot) fail('Finish bootstrap before send');
  if (state.needsSnapshot) fail('Snapshot required after retention boundary');
}

function receipt(state, response) {
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || !isText(response.mutation)) {
    fail('Foreign or invalid receipt');
  }
  return normal(response.record);
}

function wireOf(state, intent, base) {
  return {tenant: state.tenant, device: state.device, mutation: intent.mutation,
    id: intent.id, base, kind: intent.kind, data: clone(intent.data)};
}

function sendBatch(state, action) {
  requireSendable(state);
  const {batch, count} = action;
  if (!isText(batch) || !Number.isInteger(count) || count < 1 || count > MAX_BATCH) {
    fail('Invalid batch request');
  }
  const current = inflight(state);
  if (current) {
    if (current.wire.batch !== batch || current.count !== count) {
      fail('Another batch is already in flight');
    }
    return;
  }
  if (state.pending.length < count) fail('Not enough pending intents for batch');
  const selected = state.pending.slice(0, count);
  if (selected.some(intent => intent.blocked || intent.wire)) {
    fail('Batch members must be unblocked and unsent');
  }
  // Bases come from the authoritative base plus earlier selected operations.
  const predicted = {};
  const operations = selected.map(intent => {
    const base = intent.kind === 'create' ? '0'
      : own(predicted, intent.id) ?? own(state.base, intent.id)?.revision ?? '0';
    put(predicted, intent.id, increment(base));
    intent.wire = wireOf(state, intent, base);
    return {mutation: intent.mutation, id: intent.id, base, kind: intent.kind,
      data: clone(intent.data)};
  });
  state.batch = {count, wire: {tenant: state.tenant, device: state.device, batch, operations}};
}

function ackBatch(state, response) {
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || !isText(response.batch)
      || !Array.isArray(response.responses)) {
    fail('Foreign or invalid batch receipt');
  }
  const accepted = state.acceptedBatches ?? {};
  if (own(accepted, response.batch) === canonical(response)) return; // duplicate ACK_BATCH
  const current = inflight(state);
  if (!current) fail('No matching batch in flight');
  const {operations} = current.wire;
  if (response.batch !== current.wire.batch || response.responses.length !== operations.length) {
    fail('Batch receipt does not match the in-flight batch');
  }
  const records = response.responses.map((item, index) => {
    const record = receipt(state, item);
    if (item.mutation !== operations[index].mutation || record.id !== operations[index].id) {
      fail('Batch receipt membership or order mismatch');
    }
    return record;
  });
  requireNetwork(state);
  requireReceiptEpoch(state);
  for (const record of records) deliver(state, record);
  const members = new Set(operations.map(op => op.mutation));
  state.pending = state.pending.filter(p => !members.has(p.mutation));
  state.batch = null;
  state.acceptedBatches = {...accepted};
  put(state.acceptedBatches, response.batch, canonical(response));
}

function snapshotPage(state, page) {
  if (!isObject(page) || page.kind !== 'snapshot' || page.tenant !== state.tenant
      || !isText(page.epoch) || !Array.isArray(page.rows)
      || !(page.next_cursor === null || isText(page.next_cursor))) {
    fail('Invalid snapshot');
  }
  const cut = decimal(page.cut, 'cut');
  const confirmed = confirmations(page);
  const sameEpoch = page.epoch === state.epoch;
  const signature = canonical(page);
  if (!state.snapshot && !state.needsSnapshot && sameEpoch
      && state.completedPages?.includes(signature)) {
    return; // retry of an already-completed snapshot page
  }
  if (state.needsSnapshot && sameEpoch && cmp(cut, state.recoveryFloor) < 0) {
    fail('Snapshot cut precedes the retention floor');
  }
  if (!state.snapshot) {
    if (sameEpoch && cmp(cut, state.checkpoint) < 0) fail('Backward snapshot');
    state.snapshot = {epoch: page.epoch, cut, rows: {}, buffer: {}, confirmed: [], pages: []};
  }
  const stage = state.snapshot;
  if (stage.epoch !== page.epoch || stage.cut !== cut) fail('Mixed snapshot');
  for (const input of page.rows) {
    const row = normal(input);
    if (cmp(row.seq, cut) > 0) fail('Snapshot row beyond cut');
    const previous = own(stage.rows, row.id);
    if (previous && canonical(previous) !== canonical(row)) fail('Mixed snapshot row');
    put(stage.rows, row.id, row);
  }
  for (const item of confirmed) {
    if (cmp(item.seq, cut) > 0) fail('Snapshot confirmation beyond cut');
    if (!stage.confirmed.some(existing => canonical(existing) === canonical(item))) {
      stage.confirmed.push(item);
    }
  }
  if (!stage.pages.includes(signature)) stage.pages.push(signature);
  if (page.next_cursor !== null) return;

  // Atomic completion: replace base (dropping stale entities), replay
  // deliveries newer than the cut, then retire confirmed local intents.
  const base = clone(stage.rows);
  const replay = [];
  if (stage.epoch === state.epoch) replay.push(...Object.values(state.base));
  replay.push(...Object.values(stage.buffer));
  for (const record of replay) if (cmp(record.seq, cut) > 0) merge(base, record);
  state.base = base;
  stage.confirmed.sort((a, b) => cmp(a.seq, b.seq));
  reconcile(state, stage.confirmed);
  state.epoch = stage.epoch;
  state.checkpoint = cut;
  state.completedPages = stage.pages;
  state.snapshot = null;
  if (state.needsSnapshot !== undefined || state.recoveryFloor !== undefined) {
    state.needsSnapshot = false;
    state.recoveryFloor = null;
  }
}

function pullPage(state, page) {
  if (state.needsSnapshot) fail('Snapshot required after retention boundary');
  if (state.snapshot || state.epoch === null || !isObject(page) || page.kind !== 'events'
      || page.tenant !== state.tenant || page.epoch !== state.epoch
      || !Array.isArray(page.events)) {
    fail('Invalid pull context');
  }
  const from = decimal(page.from, 'from');
  const after = decimal(page.after, 'after');
  const until = decimal(page.until, 'until');
  if (cmp(from, after) > 0 || cmp(after, until) > 0) fail('Invalid page range');
  const confirmed = confirmations(page);
  if (cmp(after, state.checkpoint) <= 0) return; // already consumed
  if (from !== state.checkpoint) fail('Noncontiguous pull');
  let previous = from;
  const events = new Map();
  for (const input of page.events) {
    const row = normal(input);
    if (cmp(row.seq, previous) <= 0 || cmp(row.seq, after) > 0) fail('Event outside page');
    previous = row.seq;
    events.set(row.seq, row.id);
    merge(state.base, row);
  }
  for (const item of confirmed) {
    if (events.get(item.seq) !== item.id) fail('Confirmation does not match a page event');
  }
  reconcile(state, confirmed);
  state.checkpoint = after;
}

export function createReplica(tenant, device) {
  if (![tenant, device].every(isText)) fail('Tenant and device required');
  return {tenant, device, epoch: null, base: {}, pending: [], checkpoint: '0', snapshot: null};
}

export function reduce(input, action) {
  if (!isObject(input) || !Array.isArray(input.pending) || !isObject(input.base)) {
    fail('Invalid replica state');
  }
  const state = clone(input);
  if (!isObject(action) || typeof action.type !== 'string') fail('Invalid action');
  switch (action.type) {
    case 'QUEUE':
      unique(state, action.mutation);
      if (!isText(action.id) || !KINDS.includes(action.kind)
          || !validIntentData(action.kind, action.data)) {
        fail('Invalid intent');
      }
      state.pending.push({mutation: action.mutation, id: action.id, kind: action.kind,
        data: clone(action.data), blocked: false});
      break;
    case 'SEND': {
      requireSendable(state);
      if (inflight(state)) fail('A batch is in flight');
      const first = state.pending[0];
      if (first && !first.blocked && !first.wire) {
        const base = first.kind === 'create' ? '0' : own(state.base, first.id)?.revision ?? '0';
        first.wire = wireOf(state, first, base);
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
      const record = receipt(state, action.response);
      const mutation = action.response.mutation;
      const intent = state.pending.find(p => p.mutation === mutation);
      const operation = batchOperation(state, mutation);
      if ((intent && intent.id !== record.id) || (operation && operation.id !== record.id)) {
        fail('Receipt names a different entity');
      }
      requireReceiptEpoch(state);
      deliver(state, record);
      state.pending = state.pending.filter(p => p.mutation !== mutation);
      break;
    }
    case 'CONFLICT': {
      const intent = state.pending.find(p => p.mutation === action.mutation);
      if (!intent) fail('Unknown conflict');
      if (batchOperation(state, intent.mutation)) fail('Cannot change an in-flight batch member');
      if (action.current !== null && action.current !== undefined) {
        const current = normal(action.current);
        if (current.id !== intent.id) fail('Conflict record names a different entity');
        requireReceiptEpoch(state);
        deliver(state, current);
      }
      intent.blocked = true;
      break;
    }
    case 'RESOLVE': {
      const index = state.pending.findIndex(p => p.mutation === action.mutation);
      if (index < 0 || !state.pending[index].blocked) fail('Not a blocked intent');
      if (batchOperation(state, action.mutation)) fail('Cannot change an in-flight batch member');
      if (action.mode === 'drop') state.pending.splice(index, 1);
      else if (action.mode === 'retry') {
        unique(state, action.newMutation);
        const intent = state.pending[index];
        intent.mutation = action.newMutation;
        intent.blocked = false;
        delete intent.wire;
      } else fail('Unknown resolution');
      break;
    }
    case 'PUSH': {
      const target = state.snapshot ? state.snapshot.epoch : state.epoch;
      if (target === null || action.epoch !== target) fail('Snapshot required for epoch');
      deliver(state, action.record);
      break;
    }
    case 'RECOVERY_REQUIRED': {
      const established = state.epoch ?? state.snapshot?.epoch ?? null;
      if (established === null || action.epoch !== established) {
        fail('Recovery signal for a foreign epoch');
      }
      const floor = decimal(action.floor, 'floor');
      state.needsSnapshot = true;
      state.recoveryFloor = isText(state.recoveryFloor)
        ? maxDecimal(state.recoveryFloor, floor) : floor;
      state.snapshot = null;
      break;
    }
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
    let compatible;
    if (intent.kind === 'create') compatible = !row;
    else if (intent.kind === 'restore') compatible = Boolean(row) && row.deleted;
    else compatible = Boolean(row) && !row.deleted;
    if (intent.blocked || !compatible) {
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
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)), conflicts};
}
