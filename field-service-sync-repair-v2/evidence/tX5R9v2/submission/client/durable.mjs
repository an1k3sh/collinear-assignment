import {open, readFile, rename, unlink} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {basename, dirname, join} from 'node:path';
import {reduce} from './replica.mjs';

export async function load(path) {
  const state = JSON.parse(await readFile(path, 'utf8'));
  if (!state || typeof state !== 'object' || Array.isArray(state)
      || !Array.isArray(state.pending) || !state.base || typeof state.base !== 'object') {
    throw new Error(`Invalid replica state in ${path}`);
  }
  return state;
}

async function syncDirectory(directory) {
  let handle;
  try {
    handle = await open(directory, 'r');
    await handle.sync();
  } catch {
    // Directory fsync is unsupported on some platforms; rename is still atomic.
  } finally {
    await handle?.close();
  }
}

// Write a temporary sibling, flush it, then atomically rename over the target.
export async function save(path, state, hook) {
  const payload = JSON.stringify(state);
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomUUID()}.tmp`);
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
  await syncDirectory(dirname(path));
}

export async function sendOnce(path, exchange) {
  const state = await load(path);
  const first = state.pending[0];
  if (!first || first.blocked) return state;
  const sending = reduce(state, {type: 'SEND'});
  // Persist the immutable wire BEFORE the network side effect.
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
