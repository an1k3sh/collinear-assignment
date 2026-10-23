#!/bin/sh
set -eu
mkdir -p /app/submission
cp /solution/reconcile.py /app/submission/reconcile.py
cp /solution/REPAIR_REPORT.md /app/submission/REPAIR_REPORT.md
python /app/submission/reconcile.py --input /app/data --output /app/submission/close
