const clone = value => JSON.parse(JSON.stringify(value));
const own = (map, key) => Object.hasOwn(map, key) ? map[key] : undefined;
const put = (map, key, value) => Object.defineProperty(map, key, {
  value, enumerable: true, writable: true, configurable: true,
});
const canonical = value => JSON.stringify(value, (_, item) =>
  item && !Array.isArray(item) && typeof item === 'object'
    ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
const number = value => {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]*)$/.test(value)) {
    throw new Error('Invalid decimal string');
  }
  return BigInt(value);
};

export function createReplica(tenant, device) {
  if (![tenant, device].every(x => typeof x === 'string' && x.length)) {
    throw new Error('Tenant and device required');
  }
  return {tenant, device, epoch: null, base: {}, pending: [], checkpoint: '0', snapshot: null};
}

function merge(map, record) {
  if (!record || typeof record.id !== 'string' || !record.id) throw new Error('Invalid record');
  number(record.seq);
  const revision = number(record.revision);
  const current = own(map, record.id);
  if (!current || revision > number(current.revision)) put(map, record.id, clone(record));
  else if (revision === number(current.revision) && canonical(current) !== canonical(record)) {
    throw new Error('Conflicting records at equal revision');
  }
}

function receive(state, record, epoch) {
  const targetEpoch = state.snapshot?.epoch ?? state.epoch;
  if (targetEpoch === null || epoch !== targetEpoch) throw new Error('Snapshot required for epoch');
  if (state.snapshot) {
    if (number(record.seq) > number(state.snapshot.cut)) merge(state.snapshot.buffer, record);
    if (state.epoch === epoch) merge(state.base, record);
  } else {
    merge(state.base, record);
  }
}

function unique(state, mutation) {
  if (typeof mutation !== 'string' || !mutation || state.pending.some(p => p.mutation === mutation)) {
    throw new Error('Mutation ID must be unique');
  }
}

function confirm(state, confirmations) {
  for (const receipt of confirmations) {
    number(receipt.seq);
    if (receipt.device !== state.device) continue;
    const intent = state.pending.find(p => p.mutation === receipt.mutation);
    if (!intent) continue;
    if (intent.id !== receipt.id || !intent.wire) throw new Error('Invalid intent confirmation');
    state.pending = state.pending.filter(p => p.mutation !== receipt.mutation);
  }
}

function isBatchMember(state, mutation) {
  return state.batch?.wire.operations.some(p => p.mutation === mutation);
}

export function reduce(input, action) {
  const state = clone(input);
  if (!action || typeof action.type !== 'string') throw new Error('Invalid action');
  switch (action.type) {
    case 'QUEUE':
      unique(state, action.mutation);
      if (typeof action.id !== 'string' || !action.id
          || !['create', 'patch', 'visit', 'delete', 'restore'].includes(action.kind)
          || !action.data || Array.isArray(action.data) || typeof action.data !== 'object') {
        throw new Error('Invalid intent');
      }
      state.pending.push({mutation: action.mutation, id: action.id, kind: action.kind,
        data: clone(action.data), blocked: false});
      break;
    case 'SEND': {
      if (state.batch) throw new Error('Batch in flight');
      if (state.epoch === null || state.snapshot) throw new Error('Finish bootstrap before send');
      const first = state.pending[0];
      if (first && !first.blocked && !first.wire) {
        first.wire = {tenant: state.tenant, device: state.device, mutation: first.mutation,
          id: first.id, kind: first.kind, data: clone(first.data),
          base: own(state.base, first.id)?.revision ?? '0'};
      }
      break;
    }
    case 'SEND_BATCH': {
      if (state.epoch === null || state.snapshot) throw new Error('Finish bootstrap before send');
      if (state.batch) {
        if (state.batch.wire.batch !== action.batch || state.batch.wire.operations.length !== action.count) {
          throw new Error('Different batch in flight');
        }
        break;
      }
      if (typeof action.batch !== 'string' || !action.batch || !Number.isInteger(action.count)
          || action.count < 1 || action.count > 16 || action.count > state.pending.length) {
        throw new Error('Invalid batch');
      }
      const revisions = {};
      const operations = [];
      for (const intent of state.pending.slice(0, action.count)) {
        if (intent.blocked || intent.wire) throw new Error('Batch member already sent or blocked');
        const base = own(revisions, intent.id) ?? own(state.base, intent.id)?.revision ?? '0';
        const operation = {mutation: intent.mutation, id: intent.id, base,
          kind: intent.kind, data: clone(intent.data)};
        intent.wire = {tenant: state.tenant, device: state.device, ...operation};
        operations.push(operation);
        put(revisions, intent.id, String(number(base) + 1n));
      }
      state.batch = {wire: {tenant: state.tenant, device: state.device,
        batch: action.batch, operations}};
      break;
    }
    case 'ACK_BATCH': {
      const response = action.response;
      if (!response || response.ok !== true || response.tenant !== state.tenant
          || response.device !== state.device) throw new Error('Invalid batch receipt');
      const accepted = own(state.acceptedBatches ?? {}, response.batch);
      if (accepted) {
        if (accepted !== canonical(response)) throw new Error('Changed duplicate batch receipt');
        break;
      }
      if (!state.batch || state.batch.wire.batch !== response.batch
          || !Array.isArray(response.responses)
          || response.responses.length !== state.batch.wire.operations.length) {
        throw new Error('Incomplete or unknown batch receipt');
      }
      for (const [index, receipt] of response.responses.entries()) {
        const operation = state.batch.wire.operations[index];
        if (receipt.ok !== true || receipt.tenant !== state.tenant || receipt.device !== state.device
            || receipt.mutation !== operation.mutation || receipt.record?.id !== operation.id) {
          throw new Error('Wrong batch membership');
        }
        receive(state, receipt.record, state.snapshot?.epoch ?? state.epoch);
        state.pending = state.pending.filter(p => p.mutation !== receipt.mutation);
      }
      state.acceptedBatches ??= {};
      put(state.acceptedBatches, response.batch, canonical(response));
      state.batch = null;
      break;
    }
    case 'ACK': {
      const ack = action.response;
      if (!ack || ack.ok !== true || ack.tenant !== state.tenant || ack.device !== state.device) {
        throw new Error('Foreign or invalid receipt');
      }
      receive(state, ack.record, state.snapshot?.epoch ?? state.epoch);
      state.pending = state.pending.filter(p => p.mutation !== ack.mutation);
      break;
    }
    case 'CONFLICT': {
      if (isBatchMember(state, action.mutation)) throw new Error('Batch in flight');
      const intent = state.pending.find(p => p.mutation === action.mutation);
      if (!intent) throw new Error('Unknown conflict');
      if (action.current) receive(state, action.current, state.snapshot?.epoch ?? state.epoch);
      intent.blocked = true;
      break;
    }
    case 'RESOLVE': {
      if (isBatchMember(state, action.mutation)) throw new Error('Batch in flight');
      const index = state.pending.findIndex(p => p.mutation === action.mutation);
      if (index < 0 || !state.pending[index].blocked) throw new Error('Not a blocked intent');
      if (action.mode === 'drop') state.pending.splice(index, 1);
      else if (action.mode === 'retry') {
        unique(state, action.newMutation);
        state.pending[index].mutation = action.newMutation;
        state.pending[index].blocked = false;
        delete state.pending[index].wire;
      } else throw new Error('Unknown resolution');
      break;
    }
    case 'PUSH':
      receive(state, action.record, action.epoch);
      break;
    case 'SNAPSHOT': {
      const page = action.page;
      if (!page || page.kind !== 'snapshot' || page.tenant !== state.tenant) {
        throw new Error('Invalid snapshot');
      }
      number(page.cut);
      const signature = canonical(page);
      if (!state.snapshot && state.completedPages?.includes(signature)) break;
      if (!state.snapshot) {
        if (page.epoch === state.epoch && number(page.cut) < number(state.checkpoint)) {
          throw new Error('Backward snapshot');
        }
        state.snapshot = {epoch: page.epoch, cut: page.cut, rows: {}, buffer: {}, pages: [], confirmed: []};
        if (page.epoch === state.epoch) {
          for (const row of Object.values(state.base)) {
            if (number(row.seq) > number(page.cut)) merge(state.snapshot.buffer, row);
          }
        }
      }
      const stage = state.snapshot;
      if (stage.epoch !== page.epoch || stage.cut !== page.cut) throw new Error('Mixed snapshot');
      for (const receipt of page.confirmed ?? []) {
        if (number(receipt.seq) > number(stage.cut)) throw new Error('Confirmation beyond cut');
        stage.confirmed.push(clone(receipt));
      }
      for (const row of page.rows) {
        if (number(row.seq) > number(page.cut)) throw new Error('Snapshot row beyond cut');
        const previous = own(stage.rows, row.id);
        if (previous && canonical(previous) !== canonical(row)) throw new Error('Mixed snapshot row');
        merge(stage.rows, row);
      }
      if (!stage.pages.includes(signature)) stage.pages.push(signature);
      if (page.next_cursor === null) {
        state.base = stage.rows;
        confirm(state, stage.confirmed);
        for (const row of Object.values(stage.buffer)) merge(state.base, row);
        state.epoch = page.epoch;
        state.checkpoint = page.cut;
        state.completedPages = stage.pages;
        state.snapshot = null;
      }
      break;
    }
    case 'PULL': {
      const page = action.page;
      if (state.snapshot || state.epoch === null || page.kind !== 'events'
          || page.tenant !== state.tenant || page.epoch !== state.epoch) {
        throw new Error('Invalid pull context');
      }
      if (number(page.from) > number(page.after) || number(page.after) > number(page.until)) {
        throw new Error('Invalid page range');
      }
      if (number(page.after) <= number(state.checkpoint)) break;
      if (page.from !== state.checkpoint) throw new Error('Noncontiguous pull');
      for (const row of page.events) {
        if (number(row.seq) <= number(page.from) || number(row.seq) > number(page.after)) {
          throw new Error('Event outside page');
        }
        merge(state.base, row);
      }
      for (const receipt of page.confirmed ?? []) {
        if (number(receipt.seq) <= number(page.from) || number(receipt.seq) > number(page.after)) {
          throw new Error('Confirmation outside page');
        }
      }
      confirm(state, page.confirmed ?? []);
      state.checkpoint = page.after;
      break;
    }
    default:
      throw new Error(`Unknown action: ${action.type}`);
  }
  return state;
}

export function selectView(state) {
  const projected = clone(state.base);
  const conflicts = [];
  for (const intent of state.pending) {
    let row = own(projected, intent.id);
    const compatible = intent.kind === 'create' ? !row
      : row && (intent.kind === 'restore' ? row.deleted : !row.deleted);
    if (intent.blocked || !compatible) {
      conflicts.push(intent.mutation);
      continue;
    }
    if (intent.kind === 'create') {
      row = {id: intent.id, revision: '0', seq: '0', body: clone(intent.data), deleted: false};
      put(projected, intent.id, row);
    } else if (intent.kind === 'visit') row.body.visits += intent.data.amount;
    else if (intent.kind === 'delete') row.deleted = true;
    else {
      Object.assign(row.body, clone(intent.data));
      if (intent.kind === 'restore') row.deleted = false;
    }
  }
  return {records: Object.values(projected).filter(row => !row.deleted)
    .sort((a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0), conflicts};
}
