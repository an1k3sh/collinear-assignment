import {open, readFile, rename, unlink} from 'node:fs/promises';
import {basename, dirname, join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {reduce} from './replica.mjs';

export async function load(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

export async function save(path, state, hook) {
  const temporary = join(dirname(path), `.${basename(path)}.${randomUUID()}.tmp`);
  try {
    const handle = await open(temporary, 'wx');
    try {
      await handle.writeFile(JSON.stringify(state), 'utf8');
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
}

export async function sendOnce(path, exchange) {
  const state = await load(path);
  if (!state.pending.length || state.pending[0].blocked) return state;
  const sending = reduce(state, {type: 'SEND'});
  const wire = sending.pending[0]?.wire;
  if (!wire) return state;
  await save(path, sending);
  const response = await exchange(JSON.parse(JSON.stringify(wire)));
  const confirmed = reduce(await load(path), {type: 'ACK', response});
  await save(path, confirmed);
  return confirmed;
}

export async function sendBatchOnce(path, batch, count, exchange) {
  const state = await load(path);
  const sending = reduce(state, {type: 'SEND_BATCH', batch, count});
  await save(path, sending);
  const response = await exchange(JSON.parse(JSON.stringify(sending.batch.wire)));
  const confirmed = reduce(await load(path), {type: 'ACK_BATCH', response});
  await save(path, confirmed);
  return confirmed;
}
