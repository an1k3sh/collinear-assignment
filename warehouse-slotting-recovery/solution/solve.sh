#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/plan.py /solution/search.cpp /app/submission/
python /app/submission/plan.py --data /app/data --output /app/submission/layout.json --seed 7341
python /app/tools/evaluate.py --data /app/data --layout /app/submission/layout.json
cat > /app/submission/REPORT.md <<'EOF'
# Weekend reslotting

The search aggregates directed transition rows into symmetric pair costs
because the supplied walking distances are symmetric. The final public score
still sums every directed input row exactly as contracted.

A constrained simulated-annealing search explores same-zone pair swaps while
holding fixed SKUs and checking the labor budget. Multiple cooling restarts
are followed by steepest descent. Incremental move deltas are cross-checked
against full objective recomputation. The saved artifact was scored with the
public evaluator.

Reproduce:
`python /app/submission/plan.py --data /app/data --output /app/submission/layout.json --seed 7341`
The C++ search source and Python input/output driver are included.
EOF
