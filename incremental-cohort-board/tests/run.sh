#!/bin/bash
set -euo pipefail
mkdir -p /logs/verifier
# A verifier exception must never leave a stale positive reward.
printf '{"overall":0.0,"functional_correctness":0.0,"constraint_satisfaction":0.0,"robustness":0.0,"artifact_quality":0.0}\n' > /logs/verifier/reward.json
cd /app
python /tests/test_projection.py

