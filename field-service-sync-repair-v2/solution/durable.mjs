import {readFile, writeFile, rename, unlink} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {reduce} from './replica.mjs';

export async function load(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

export async function save(path, state, hook) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, JSON.stringify(state), {encoding: 'utf8', flag: 'wx'});
    if (hook) await hook('before_rename');
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch(error => {
      if (error.code !== 'ENOENT') throw error;
    });
  }
}

export async function sendOnce(path, exchange) {
  const state = await load(path);
  if (state.batch) throw new Error('Batch in flight');
  if (!state.pending.length || state.pending[0].blocked) return state;
  const sending = reduce(state, {type: 'SEND'});
  await save(path, sending);
  const response = await exchange(sending.pending[0].wire);
  const confirmed = reduce(sending, {type: 'ACK', response});
  await save(path, confirmed);
  return confirmed;
}

export async function sendBatchOnce(path, batch, count, exchange) {
  const state = await load(path);
  const sending = reduce(state, {type: 'SEND_BATCH', batch, count});
  await save(path, sending);
  const response = await exchange(sending.batch.wire);
  const confirmed = reduce(sending, {type: 'ACK_BATCH', response});
  await save(path, confirmed);
  return confirmed;
}
