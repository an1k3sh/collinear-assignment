#!/bin/bash
set -euo pipefail
export PHASE=2
mkdir -p /logs/verifier
printf '{"overall":0}\n' > /logs/verifier/reward.json
python /tests/test_settlement.py
