#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/analyze.py /solution/observations.json /solution/audit.json /solution/audit.md /app/submission/
python /app/submission/analyze.py --observations /app/submission/observations.json \
  --policy /app/policy.json --out /app/submission/analysis.json
