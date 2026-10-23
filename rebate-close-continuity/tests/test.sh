#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
# Leave an explicit failure reward if the grader itself crashes.
printf '{"overall":0,"functional_correctness":0,"constraint_satisfaction":0,"robustness":0,"artifact_quality":0}\n' > /logs/verifier/reward.json
python /tests/test_settlement.py
