#!/bin/sh
set -eu
cp /solution/stockroom/*.py /app/stockroom/
cp /solution/fulfill.stock /app/workflows/fulfill.stock
mkdir -p /app/deliverable
cd /app
python -m stockroom /app/incident/run.stock \
  --library /app/workflows/fulfill.stock \
  --inventory /app/incident/inventory.json \
  --out /app/deliverable/result.json
cat > /app/deliverable/HANDOFF.md <<'EOF'
# Reference implementation handoff

Implemented a tokenizer, precedence parser and whole-program type/call-graph
checker, followed by an AST interpreter. Procedure environments are isolated;
rollback restores active binding dictionaries in place. Transaction snapshots
include stock, hold tombstones and buffered events, but exclude diagnostic
counters. Successful control-transfer signals are separate from domain faults.
Publication uses a temporary sibling and atomic replacement.

Executed the incident CLI successfully. Practice was rolled back, alpha used
west, beta used east, gamma was deferred, and delta used east after the safety
hold was released. Final east gear/seal: 3/0; west gear/seal: 3/6. All holds
remaining in the committed incident state are closed.
EOF
