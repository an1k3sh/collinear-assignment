import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import traceback

from check_plan import Check

ROOT=Path("/app")
LOGS=Path("/logs/verifier")
LOGS.mkdir(parents=True,exist_ok=True)
details={}


def check(name,function):
    try:
        function()
        details[name]={"passed":True}
    except Exception:
        details[name]={"passed":False,"error":traceback.format_exc()}


def candidate():
    return Check(ROOT/"data",json.loads((ROOT/"submission/topology.json").read_text()),
                 json.loads((ROOT/"submission/maintenance.json").read_text()))


def integrity():
    for name,digest in json.loads(Path("/tests/protected.json").read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, "Changed protected input: "+name


def regenerate():
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        shutil.copytree(ROOT/"data",folder/"records")
        shutil.copy2(ROOT/"submission/topology.json",folder/"topology.json")
        output=folder/"release"/"maintenance.json"
        output.parent.mkdir()
        process=subprocess.run(
            ["python",str(ROOT/"submission/build_plan.py"),"--data",str(folder/"records"),
             "--topology",str(folder/"topology.json"),"--output",str(output)],
            cwd=folder,text=True,capture_output=True,timeout=180)
        (LOGS/"regeneration.txt").write_text(process.stdout+"\n"+process.stderr)
        assert process.returncode==0, "Planner failed: "+process.stderr[-3000:]
        Check(folder/"records",json.loads((folder/"topology.json").read_text()),json.loads(output.read_text())).all()


def handover():
    assert (ROOT/"submission/handover.md").read_text().strip(), "Missing handover"


check("input_integrity",integrity)
for name in ("transcription","coverage","connectivity","availability","protection","capacity","budget"):
    check(name,lambda name=name:getattr(candidate(),name)())
check("regeneration",regenerate)
check("handover",handover)
rewards={k:float(v["passed"]) for k,v in details.items()}
rewards["overall"]=float(all(rewards.values()))
(LOGS/"details.json").write_text(json.dumps(details,indent=2)+"\n")
(LOGS/"reward.json").write_text(json.dumps(rewards,indent=2)+"\n")
print(json.dumps(rewards,indent=2))
