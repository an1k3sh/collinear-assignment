#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/analyze.py /solution/readings.json /solution/audit.json /solution/decision.md /app/submission/
python /app/submission/analyze.py --readings /app/submission/readings.json \
  --manifest /app/export-manifest.json --operations /app/operations.json \
  --planning /app/planning.json --registry /app/registry.csv --out /app/submission/analysis.json
