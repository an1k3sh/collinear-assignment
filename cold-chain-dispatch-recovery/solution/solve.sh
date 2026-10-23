#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/build_plan.py /app/submission/build_plan.py
python /app/submission/build_plan.py --data /app/data --output /app/submission/plan.json
cat > /app/submission/dispatch-note.md <<'EOF'
# Depot release

The roster selects the last cutoff-known complete order version before applying
status/effectivity. Stock is deduplicated within warehouse namespaces, and the
last cutoff-known quality disposition controls release. Lot balances, packing
availability and delivery-end expiry are jointly constrained.

The planner uses directed travel and integer intervals. It coordinates packing
bench breaks, the single loading dock, vehicle turnaround, complete customer
windows, capacity and thermal life through customer service completion.
Hiring, trip fees and driving charges are included in the reported spend, which
is bounded by the manager's authorization. The solver's selected integer
schedule is the dispatch artifact; route permutations need not be unique.
EOF
