import {readFileSync} from 'node:fs';
import {createReplica, reduce, selectView} from './replica.mjs';

const input = JSON.parse(readFileSync(0, 'utf8'));
let state = input.state ?? createReplica(input.tenant ?? 'north', input.device ?? 'van-7');
for (const action of input.actions) state = reduce(state, action);
console.log(JSON.stringify({state, view: selectView(state)}));
