import {open, readFile, rename, unlink} from 'node:fs/promises';
import {basename, dirname, join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {reduce} from './replica.mjs';

export async function load(path) {
  const state = JSON.parse(await readFile(path, 'utf8'));
  if (!state || typeof state !== 'object' || Array.isArray(state)
      || !Array.isArray(state.pending) || !state.base || typeof state.base !== 'object') {
    throw new Error(`Invalid replica state in ${path}`);
  }
  return state;
}

// Write a temporary sibling, flush it, then atomically replace the target.
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
    await unlink(temporary).catch(cleanup => {
      if (cleanup.code !== 'ENOENT') error.cleanupError = cleanup;
    });
    throw error;
  }
}

// Persist the immutable wire BEFORE the network side effect; a transport error
// propagates and leaves that wire on disk for an identical retry.
export async function sendOnce(path, exchange) {
  const state = await load(path);
  if (state.needsSnapshot) reduce(state, {type: 'SEND'}); // surfaces the recovery error
  if (!state.pending.length || state.pending[0].blocked) return state;
  const sending = reduce(state, {type: 'SEND'});
  await save(path, sending);
  const response = await exchange(structuredClone(sending.pending[0].wire));
  const confirmed = reduce(await load(path), {type: 'ACK', response});
  await save(path, confirmed);
  return confirmed;
}

export async function sendBatchOnce(path, batch, count, exchange) {
  const state = await load(path);
  const sending = reduce(state, {type: 'SEND_BATCH', batch, count});
  await save(path, sending);
  const response = await exchange(structuredClone(sending.batch.wire));
  const confirmed = reduce(await load(path), {type: 'ACK_BATCH', response});
  await save(path, confirmed);
  return confirmed;
}
