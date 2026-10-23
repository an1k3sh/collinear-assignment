import {open, readFile, rename, unlink} from 'node:fs/promises';
import {dirname, basename, join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {reduce} from './replica.mjs';

export async function load(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

// Write a temporary sibling, flush it, then atomically rename over the target.
export async function save(path, state, hook) {
  const payload = JSON.stringify(state);
  const temporary = join(dirname(path), `.${basename(path)}.${randomUUID()}.tmp`);
  try {
    const handle = await open(temporary, 'wx');
    try {
      await handle.writeFile(payload, 'utf8');
      await handle.sync();
    } finally {
      await handle.close();
    }
    if (hook) await hook('before_rename');
    await rename(temporary, path);
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  }
  try {
    const directory = await open(dirname(path), 'r');
    try { await directory.sync(); } finally { await directory.close(); }
  } catch {
    // Directory fsync is unsupported on some platforms; the rename is already atomic.
  }
}

export async function sendOnce(path, exchange) {
  const state = await load(path);
  if (!state.pending.length || state.pending[0].blocked) return state;
  const sending = reduce(state, {type: 'SEND'});
  await save(path, sending);
  const response = await exchange(structuredClone(sending.pending[0].wire));
  const confirmed = reduce(sending, {type: 'ACK', response});
  await save(path, confirmed);
  return confirmed;
}

export async function sendBatchOnce(path, batch, count, exchange) {
  const state = await load(path);
  const sending = reduce(state, {type: 'SEND_BATCH', batch, count});
  await save(path, sending);
  const response = await exchange(structuredClone(sending.batch.wire));
  const confirmed = reduce(sending, {type: 'ACK_BATCH', response});
  await save(path, confirmed);
  return confirmed;
}
