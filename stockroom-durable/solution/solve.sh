#!/bin/sh
set -eu
cp /solution/stockroom/*.py /app/stockroom/
cp /solution/fulfill.stock /app/workflows/fulfill.stock
mkdir -p /app/deliverable
cd /app
set -- python -m stockroom /app/incident/run.stock \
  --library /app/workflows/fulfill.stock \
  --inventory /app/incident/inventory.json \
  --out /app/deliverable/result.json \
  --checkpoint /app/deliverable/checkpoint.json
status=0
"$@" || status=$?
while [ "$status" -eq 10 ]; do
  status=0
  "$@" --resume /app/deliverable/checkpoint.json || status=$?
done
if [ "$status" -ne 0 ]; then exit "$status"; fi
cat > /app/deliverable/HANDOFF.md <<'EOF'
# Durable interpreter handoff

Built a tokenizer, precedence parser, static scope/type/call-graph validator,
and a serializable continuation machine. Scope IDs preserve rollback targets;
call, loop, scope and transaction boundaries are explicit stack entries.
Checkpoints include active snapshots, error bindings and cumulative counters;
the envelope binds exact source/library/inventory bytes and checks its digest.

Executed the incident through seven suspensions using separate CLI processes:
practice:reserved, rehearsal:before-abort, ASSERT, alpha:reserved,
dispatch:after-alpha, beta:reserved, delta:reserved.
The rehearsal's previously saved transaction rolled back. Alpha used west,
beta used east, gamma was deferred and delta used east. Final east gear/seal:
3/0; west gear/seal: 3/6. Closed holds and event order are preserved.
The last checkpoint is retained and can be replayed into another result file.
EOF
