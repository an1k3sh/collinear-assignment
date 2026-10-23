#!/bin/bash
set -euo pipefail
cd /workspace
cp /solution/refresh_oracle.py refresh.py
cp /solution/plan_oracle.py plan.py
python - <<'PY'
import json
import subprocess
from pathlib import Path
turn = json.loads(Path("inputs/turn.json").read_text())
args = ["python", "refresh.py", "--source", "inputs/source.xlsx", "--as-of",
        turn["as_of"], "--output", "output/settlement.xlsx"]
prior = {2: 1, 3: 2, 4: 2, 5: 3}.get(turn["phase"])
if prior:
    args.extend(["--previous", f'output/archive/close-{prior}.xlsx'])
subprocess.run(args, check=True)
if turn["phase"] >= 4:
    args = ["python", "plan.py", "--settlement", "output/settlement.xlsx",
            "--claims", "inputs/claims.xlsx", "--as-of", turn["as_of"],
            "--output", "output/claim-plan.xlsx"]
    if turn["phase"] == 5:
        args.extend(["--prior-plan", "output/archive/claim-plan-1.xlsx"])
    subprocess.run(args, check=True)
PY
