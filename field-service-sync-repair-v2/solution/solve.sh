#!/bin/sh
set -eu
cp /solution/store.py /app/server/store.py
cp /solution/replica.mjs /app/client/replica.mjs
cp /solution/durable.mjs /app/client/durable.mjs
python3 /app/tools/repair.py --db /app/state/site.sqlite
cp /solution/REPAIR_REPORT.md /app/REPAIR_REPORT.md
cp /solution/regressions.py /app/tests/regressions.py
python3 /app/tests/regressions.py
