import {readFile, writeFile, rename, unlink} from 'node:fs/promises';
import {randomUUID} from 'node:crypto';
import {reduce} from './replica.mjs';

export async function load(path) {
  return JSON.parse(await readFile(path, 'utf8'));
}

export async function save(path, state, hook) {
  await writeFile(path, JSON.stringify(state), 'utf8');
  if (hook) await hook('before_rename');
}

export async function sendOnce(path, exchange) {
  const state = await load(path);
  if (!state.pending.length || state.pending[0].blocked) return state;
  const sending = reduce(state, {type: 'SEND'});
  const response = await exchange(sending.pending[0].wire);
  const confirmed = reduce(sending, {type: 'ACK', response});
  await save(path, confirmed);
  return confirmed;
}
