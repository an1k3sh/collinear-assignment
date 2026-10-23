#!/bin/sh
set -eu
mkdir -p /logs/verifier
printf '{"overall":0.0}\n' > /logs/verifier/reward.json
python /tests/protect.py
python /tests/grade.py
