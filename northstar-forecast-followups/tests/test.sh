#!/bin/sh
set -eu
mkdir -p /logs/verifier
cd /app
python /tests/grade_phase.py --phase "$PHASE"
