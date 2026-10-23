import {readFileSync} from 'node:fs';
import {createReplica, reduce, selectView} from './replica.mjs';

try {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  if (!input || typeof input !== 'object' || !Array.isArray(input.actions)) {
    throw new Error('Trace input must be an object with an actions array');
  }
  let state = input.state ?? createReplica(input.tenant ?? 'north', input.device ?? 'van-7');
  for (const [index, action] of input.actions.entries()) {
    try {
      state = reduce(state, action);
    } catch (error) {
      throw new Error(`action ${index} (${action?.type}): ${error.message}`);
    }
  }
  console.log(JSON.stringify({state, view: selectView(state)}));
} catch (error) {
  process.stderr.write(`trace: ${error.message}\n`);
  process.exitCode = 1;
}
