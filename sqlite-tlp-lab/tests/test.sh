#!/bin/sh
set -eu
TEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VERIFIER_LOG=${VERIFIER_LOG:-/logs/verifier}
export VERIFIER_LOG
mkdir -p "$VERIFIER_LOG"
printf '{"overall":0.0,"validity":0.0,"oracle_correctness":0.0,"input_validity_rate":0.0,"completeness":0.0,"diversity":0.0,"artifact_quality":0.0}\n' > "$VERIFIER_LOG/reward.json"
exec python "$TEST_ROOT/grade.py"
