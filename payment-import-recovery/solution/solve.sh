#!/bin/sh
set -eu
cp /solution/import_payments.py /app/import_payments.py
mkdir -p /app/submission /app/tests
cp /solution/test_regression.py /app/tests/test_regression.py
cp /solution/REPAIR_REPORT.md /app/submission/REPAIR_REPORT.md
cd /app
python import_payments.py --db state/payments.sqlite --input data/payments.csv --report submission/import-report.json
python -m unittest discover -s tests
