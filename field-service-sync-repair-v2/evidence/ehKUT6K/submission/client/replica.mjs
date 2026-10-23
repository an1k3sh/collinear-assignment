// Offline work-order replica. State is plain JSON: decimal strings stay strings and
// BigInt is only used transiently for comparisons/arithmetic.

const clone = value => JSON.parse(JSON.stringify(value));
const own = (map, key) => Object.hasOwn(map, key) ? map[key] : undefined;
const put = (map, key, value) => Object.defineProperty(map, key, {
  value, enumerable: true, writable: true, configurable: true,
});
const canonical = value => JSON.stringify(value, (_, item) =>
  item && !Array.isArray(item) && typeof item === 'object'
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);

const MAX_VISITS = 9007199254740991;
const MAX_BATCH = 16;
const KINDS = ['create', 'patch', 'visit', 'delete', 'restore'];
const BODY_FIELDS = ['title', 'assignee', 'visits', 'done'];

const fail = message => { throw new Error(message); };
const isObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const isText = value => typeof value === 'string' && value.length > 0 && value.isWellFormed();

function decimal(value, what = 'decimal') {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) {
    fail(`Invalid ${what}: expected canonical decimal string`);
  }
  return BigInt(value);
}
const cmp = (a, b) => {
  const x = decimal(a), y = decimal(b);
  return x < y ? -1 : x > y ? 1 : 0;
};

// Code point order, matching the server's UTF-8 binary ordering.
function compareIds(a, b) {
  const x = [...a], y = [...b];
  for (let i = 0; i < Math.min(x.length, y.length); i += 1) {
    const d = x[i].codePointAt(0) - y[i].codePointAt(0);
    if (d) return d;
  }
  return x.length - y.length;
}

function checkBody(value, partial) {
  if (!isObject(value)) fail('Invalid body');
  const keys = Object.keys(value);
  if (keys.some(key => !BODY_FIELDS.includes(key))) fail('Unknown body field');
  if (!partial && keys.length !== BODY_FIELDS.length) fail('Incomplete body');
  for (const key of keys) {
    const item = value[key];
    const valid = {
      title: isText(item),
      assignee: item === null || (typeof item === 'string' && item.isWellFormed()),
      visits: Number.isSafeInteger(item) && item >= 0 && item <= MAX_VISITS,
      done: typeof item === 'boolean',
    }[key];
    if (!valid) fail(`Invalid body field: ${key}`);
  }
}

function checkData(kind, data) {
  if (!KINDS.includes(kind)) fail('Invalid intent kind');
  if (!isObject(data)) fail('Invalid intent data');
  if (kind === 'create') checkBody(data, false);
  else if (kind === 'patch' || kind === 'restore') checkBody(data, true);
  else if (kind === 'visit') {
    if (Object.keys(data).length !== 1 || !Number.isSafeInteger(data.amount)
        || data.amount <= 0) fail('Invalid visit amount');
  } else if (Object.keys(data).length) fail('Delete takes no data');
}

function normalizeRecord(record) {
  if (!isObject(record) || !isText(record.id)) fail('Invalid record');
  decimal(record.revision, 'record revision');
  decimal(record.seq, 'record seq');
  if (typeof record.deleted !== 'boolean') fail('Invalid record deletion flag');
  checkBody(record.body, false);
  return {id: record.id, revision: record.revision, body: clone(record.body),
    deleted: record.deleted, seq: record.seq};
}

// Merge only strictly newer revisions; an equal revision must be the same record.
function merge(map, input) {
  const record = normalizeRecord(input);
  const current = own(map, record.id);
  if (!current) {
    put(map, record.id, record);
    return;
  }
  const order = cmp(record.revision, current.revision);
  if (order > 0) put(map, record.id, record);
  else if (order === 0 && canonical(current) !== canonical(record)) {
    fail(`Conflicting records at equal revision for ${record.id}`);
  }
}

function normalizeConfirmations(list) {
  if (list === undefined) return [];
  if (!Array.isArray(list)) fail('Invalid confirmations');
  return list.map(item => {
    if (!isObject(item) || !isText(item.device) || !isText(item.mutation) || !isText(item.id)) {
      fail('Invalid confirmation');
    }
    decimal(item.seq, 'confirmation seq');
    return {device: item.device, mutation: item.mutation, id: item.id, seq: item.seq};
  });
}

export function createReplica(tenant, device) {
  if (![tenant, device].every(isText)) fail('Tenant and device required');
  return {tenant, device, epoch: null, base: {}, pending: [], checkpoint: '0',
    snapshot: null, batch: null};
}

function checkState(state) {
  if (!isObject(state) || !isText(state.tenant) || !isText(state.device)
      || !isObject(state.base) || !Array.isArray(state.pending)) {
    fail('Invalid replica state');
  }
  decimal(state.checkpoint, 'checkpoint');
  state.snapshot ??= null;
  state.batch ??= null;
}

function bootstrapped(state) {
  if (state.epoch === null || state.epoch === undefined) fail('Snapshot required before sync');
}

const inBatch = (state, mutation) =>
  Boolean(state.batch?.wire.operations.some(op => op.mutation === mutation));

function unique(state, mutation) {
  if (!isText(mutation)) fail('Mutation ID required');
  if (state.pending.some(p => p.mutation === mutation) || inBatch(state, mutation)) {
    fail('Mutation ID must be unique');
  }
}

// Remote delivery outside pull/snapshot pages: ACK, CONFLICT, PUSH records.
function deliver(state, record, epoch) {
  if (state.snapshot) {
    if (epoch !== state.snapshot.epoch) fail('Delivery epoch does not match snapshot');
    merge(state.snapshot.buffer, record);
    if (state.epoch === epoch) merge(state.base, record);
  } else {
    bootstrapped(state);
    if (epoch !== state.epoch) fail('Snapshot required for epoch');
    merge(state.base, record);
  }
}
const liveEpoch = state => state.snapshot ? state.snapshot.epoch : state.epoch;

// Retire pending intents proven committed by authoritative confirmations.
function confirm(state, confirmations) {
  const retired = new Set();
  for (const item of confirmations) {
    if (item.device !== state.device) continue;
    const op = state.batch?.wire.operations.find(o => o.mutation === item.mutation);
    if (op && op.id !== item.id) fail(`Confirmation entity mismatch for ${item.mutation}`);
    const intent = state.pending.find(p => p.mutation === item.mutation);
    if (!intent) continue;
    if (intent.id !== item.id) fail(`Confirmation entity mismatch for ${item.mutation}`);
    if (!intent.wire) fail(`Confirmation for unsent intent ${item.mutation}`);
    retired.add(item.mutation);
  }
  state.pending = state.pending.filter(p => !retired.has(p.mutation));
}

function capture(state, intent, base) {
  intent.wire = {tenant: state.tenant, device: state.device, mutation: intent.mutation,
    id: intent.id, base, kind: intent.kind, data: clone(intent.data)};
  return intent.wire;
}

function canSend(state) {
  bootstrapped(state);
  if (state.snapshot && state.snapshot.epoch !== state.epoch) {
    fail('Finish bootstrap of the new epoch before send');
  }
}

function pageHash(page) { // compact deterministic fingerprint of a JSON value
  const text = canonical(page);
  let a = 0x811c9dc5, b = 0x01000193;
  for (let i = 0; i < text.length; i += 1) {
    const c = text.charCodeAt(i);
    a = Math.imul(a ^ c, 0x01000193) >>> 0;
    b = Math.imul(b ^ c, 0x5bd1e995) >>> 0;
  }
  return `${text.length}:${a.toString(16)}:${b.toString(16)}`;
}

function snapshotPage(state, page) {
  if (!isObject(page) || page.kind !== 'snapshot' || page.tenant !== state.tenant
      || !isText(page.epoch) || !Array.isArray(page.rows)
      || !(page.next_cursor === null || typeof page.next_cursor === 'string')) {
    fail('Invalid snapshot page');
  }
  decimal(page.cut, 'snapshot cut');
  const rows = page.rows.map(normalizeRecord);
  const confirmations = normalizeConfirmations(page.confirmed);
  for (const row of rows) {
    if (cmp(row.seq, page.cut) > 0) fail('Snapshot row beyond cut');
  }
  for (const item of confirmations) {
    if (cmp(item.seq, page.cut) > 0) fail('Snapshot confirmation beyond cut');
  }
  const signature = pageHash(page);
  if (!state.snapshot) {
    const done = state.completedSnapshot;
    if (done && done.epoch === page.epoch && done.cut === page.cut
        && done.pages.includes(signature)) return; // retried page of a completed snapshot
    if (page.epoch === state.epoch && cmp(page.cut, state.checkpoint) < 0) {
      fail('Backward snapshot cut');
    }
    const buffer = {};
    if (page.epoch === state.epoch) {
      for (const row of Object.values(state.base)) {
        if (cmp(row.seq, page.cut) > 0) merge(buffer, row);
      }
    }
    state.snapshot = {epoch: page.epoch, cut: page.cut, rows: {}, confirmed: [],
      buffer, pages: []};
  }
  const stage = state.snapshot;
  if (stage.epoch !== page.epoch || stage.cut !== page.cut) fail('Mixed snapshot epoch/cut');
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
  if (!stage.pages.includes(signature)) stage.pages.push(signature);
  if (page.next_cursor !== null) {
    stage.next = page.next_cursor; // lets a restarted client resume the same frozen cut
    return;
  }
  // Completion: atomically replace base, reconcile, replay post-cut deliveries.
  const base = {};
  for (const row of Object.values(stage.rows)) put(base, row.id, row);
  for (const row of Object.values(stage.buffer)) {
    if (cmp(row.seq, stage.cut) > 0) merge(base, row);
  }
  state.base = base;
  confirm(state, stage.confirmed);
  state.epoch = stage.epoch;
  state.checkpoint = stage.cut;
  state.completedSnapshot = {epoch: stage.epoch, cut: stage.cut, pages: stage.pages};
  state.snapshot = null;
}

function pullPage(state, page) {
  if (state.snapshot) fail('Pull while snapshot is in progress');
  bootstrapped(state);
  if (!isObject(page) || page.kind !== 'events' || page.tenant !== state.tenant
      || page.epoch !== state.epoch || !Array.isArray(page.events)) {
    fail('Invalid pull context');
  }
  if (cmp(page.from, page.after) > 0 || cmp(page.after, page.until) > 0) {
    fail('Invalid page range');
  }
  const events = page.events.map(normalizeRecord);
  const confirmations = normalizeConfirmations(page.confirmed);
  if (cmp(page.after, state.checkpoint) <= 0) return; // already consumed
  if (page.from !== state.checkpoint) fail('Noncontiguous pull page');
  const bySeq = new Map();
  for (const row of events) {
    if (cmp(row.seq, page.from) <= 0 || cmp(row.seq, page.after) > 0) {
      fail('Event outside page');
    }
    bySeq.set(row.seq, row);
  }
  for (const item of confirmations) {
    const event = bySeq.get(item.seq);
    if (!event || event.id !== item.id) fail('Confirmation does not match page events');
  }
  for (const row of events) merge(state.base, row);
  confirm(state, confirmations);
  state.checkpoint = page.after;
}

function receipt(state, response) {
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || !isText(response.mutation)) {
    fail('Foreign or invalid receipt');
  }
  return normalizeRecord(response.record);
}

function sendBatch(state, action) {
  const {batch, count} = action;
  if (!isText(batch) || !Number.isInteger(count) || count < 1 || count > MAX_BATCH) {
    fail('Invalid batch request');
  }
  if (state.batch) {
    if (state.batch.wire.batch !== batch || state.batch.count !== count) {
      fail('Another batch is in flight');
    }
    return;
  }
  canSend(state);
  if (state.pending.length < count) fail('Not enough pending intents for batch');
  const selected = state.pending.slice(0, count);
  if (selected.some(p => p.blocked || p.wire)) fail('Batch members must be unsent and unblocked');
  const predicted = new Map();
  const operations = selected.map(intent => {
    const base = predicted.get(intent.id) ?? own(state.base, intent.id)?.revision ?? '0';
    predicted.set(intent.id, (decimal(base) + 1n).toString());
    const {tenant, device, ...operation} = capture(state, intent, base);
    return clone(operation);
  });
  state.batch = {wire: {tenant: state.tenant, device: state.device, batch, operations}, count};
}

const ACCEPTED_BATCH_HISTORY = 64;

function ackBatch(state, response) {
  const accepted = state.acceptedBatches ?? {};
  if (isObject(response) && typeof response.batch === 'string'
      && own(accepted, response.batch) === pageHash(response)) return; // duplicate ACK_BATCH
  if (!state.batch) fail('No batch in flight');
  const wire = state.batch.wire;
  if (!isObject(response) || response.ok !== true || response.tenant !== state.tenant
      || response.device !== state.device || response.batch !== wire.batch
      || !Array.isArray(response.responses)
      || response.responses.length !== wire.operations.length) {
    fail('Batch receipt does not match in-flight batch');
  }
  const records = response.responses.map((item, index) => {
    const record = receipt(state, item);
    const op = wire.operations[index];
    if (item.mutation !== op.mutation || record.id !== op.id) {
      fail('Batch receipt membership/order mismatch');
    }
    return record;
  });
  for (const record of records) deliver(state, record, liveEpoch(state));
  const members = new Set(wire.operations.map(op => op.mutation));
  state.pending = state.pending.filter(p => !members.has(p.mutation));
  state.batch = null;
  const history = Object.entries(accepted).filter(([batch]) => batch !== wire.batch);
  history.push([wire.batch, pageHash(response)]);
  state.acceptedBatches = {};
  for (const [batch, hash] of history.slice(-ACCEPTED_BATCH_HISTORY)) {
    put(state.acceptedBatches, batch, hash);
  }
}

export function reduce(input, action) {
  const state = clone(input);
  checkState(state);
  if (!isObject(action) || typeof action.type !== 'string') fail('Invalid action');
  switch (action.type) {
    case 'QUEUE':
      unique(state, action.mutation);
      if (!isText(action.id)) fail('Invalid intent entity');
      checkData(action.kind, action.data);
      state.pending.push({mutation: action.mutation, id: action.id, kind: action.kind,
        data: clone(action.data), blocked: false});
      break;
    case 'SEND': {
      bootstrapped(state);
      if (state.batch) fail('Batch in flight');
      const first = state.pending[0];
      if (!first || first.blocked || first.wire) break;
      canSend(state);
      capture(state, first, own(state.base, first.id)?.revision ?? '0');
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
      if (intent) {
        if (intent.id !== record.id) fail('Receipt entity does not match intent');
        if (!intent.wire) fail('Receipt for unsent intent');
      }
      deliver(state, record, liveEpoch(state));
      state.pending = state.pending.filter(p => p.mutation !== mutation);
      break;
    }
    case 'CONFLICT': {
      const intent = state.pending.find(p => p.mutation === action.mutation);
      if (!intent) fail('Unknown conflict');
      if (inBatch(state, intent.mutation)) fail('Cannot change a member of an in-flight batch');
      if (!intent.wire) fail('Conflict for unsent intent');
      if (action.current !== null && action.current !== undefined) {
        const current = normalizeRecord(action.current);
        if (current.id !== intent.id) fail('Conflict record does not match intent');
        deliver(state, current, liveEpoch(state));
      }
      intent.blocked = true;
      break;
    }
    case 'RESOLVE': {
      const index = state.pending.findIndex(p => p.mutation === action.mutation);
      if (index < 0 || !state.pending[index].blocked) fail('Not a blocked intent');
      if (inBatch(state, action.mutation)) fail('Cannot change a member of an in-flight batch');
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
    case 'PUSH':
      if (!isText(action.epoch)) fail('Push epoch required');
      deliver(state, action.record, action.epoch);
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
    const row = own(projected, intent.id);
    let compatible = intent.kind === 'create' ? !row
      : intent.kind === 'restore' ? Boolean(row?.deleted)
        : Boolean(row && !row.deleted);
    // The server rejects totals above 2^53-1; never project an out-of-range count.
    if (compatible && intent.kind === 'visit'
        && row.body.visits + intent.data.amount > MAX_VISITS) compatible = false;
    if (intent.blocked || !compatible) {
      conflicts.push(intent.mutation);
      continue;
    }
    if (intent.kind === 'create') {
      put(projected, intent.id, {id: intent.id, revision: '0', seq: '0',
        body: clone(intent.data), deleted: false});
    } else if (intent.kind === 'visit') row.body.visits += intent.data.amount;
    else if (intent.kind === 'delete') row.deleted = true;
    else {
      Object.assign(row.body, clone(intent.data));
      row.deleted = false;
    }
  }
  return {records: Object.values(projected).filter(row => !row.deleted)
    .sort((a, b) => compareIds(a.id, b.id)), conflicts};
}
