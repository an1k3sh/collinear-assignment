import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import traceback

from check_plan import CheckPlan

ROOT = Path("/app")
LOGS = Path("/logs/verifier")
LOGS.mkdir(parents=True, exist_ok=True)
details = {}


def check(name, function):
    try:
        function()
        details[name] = {"passed":True}
    except Exception:
        details[name] = {"passed":False,"error":traceback.format_exc()}


def integrity():
    manifest = json.loads(Path("/tests/protected.json").read_text())
    for name, digest in manifest.items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest, f"Protected input changed: {name}"


def candidate():
    return CheckPlan(ROOT/"data",json.loads((ROOT/"submission/plan.json").read_text()))


def regenerate():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        shutil.copytree(ROOT/"data",folder/"source")
        output = folder/"release"/"plan.json"
        output.parent.mkdir()
        process = subprocess.run(
            ["python",str(ROOT/"submission/build_plan.py"),"--data",str(folder/"source"),"--output",str(output)],
            cwd=folder,capture_output=True,text=True,timeout=180)
        (LOGS/"regeneration.txt").write_text(process.stdout+"\n"+process.stderr)
        assert process.returncode == 0, f"Regeneration failed: {process.stderr[-3000:]}"
        CheckPlan(folder/"source",json.loads(output.read_text())).all()


def note():
    assert (ROOT/"submission/dispatch-note.md").read_text().strip(), "Missing operational handover"


check("input_integrity",integrity)
for criterion in ("roster","allocations","packing","trips","cold_chain","cost"):
    check(criterion,lambda name=criterion:getattr(candidate(),name)())
check("regeneration",regenerate)
check("handover",note)
rewards = {k:float(v["passed"]) for k,v in details.items()}
rewards["overall"] = float(all(rewards.values()))
(LOGS/"details.json").write_text(json.dumps(details,indent=2)+"\n")
(LOGS/"reward.json").write_text(json.dumps(rewards,indent=2)+"\n")
print(json.dumps(rewards,indent=2))
