import {readFileSync} from 'node:fs';
import {createReplica, reduce, selectView} from './replica.mjs';

try {
  const input = JSON.parse(readFileSync(0, 'utf8'));
  if (!input || typeof input !== 'object' || !Array.isArray(input.actions)) {
    throw new Error('Trace input requires an actions array');
  }
  let state = input.state ?? createReplica(input.tenant ?? 'north', input.device ?? 'van-7');
  input.actions.forEach((action, index) => {
    try {
      state = reduce(state, action);
    } catch (error) {
      throw new Error(`Action ${index} (${action?.type}): ${error.message}`);
    }
  });
  process.stdout.write(`${JSON.stringify({state, view: selectView(state)})}\n`);
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
