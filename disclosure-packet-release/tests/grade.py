import hashlib
import json
from pathlib import Path
import traceback

from check_packet import Packet

ROOT=Path("/app")
LOGS=Path("/logs/verifier")
details={}


def check(name,function):
    try:
        function()
        details[name]={"passed":True}
    except Exception:
        details[name]={"passed":False,"error":traceback.format_exc()}


def inputs():
    for name,digest in json.loads(Path("/tests/protected.json").read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest, "Original input changed: "+name


def contents():
    assert {p.name for p in (ROOT/"submission").iterdir()}=={"release.pdf","release-note.md"}, "Unexpected public release files"
    assert (ROOT/"submission/release-note.md").read_text().strip(), "Missing public release note"


if __name__=="__main__":
    LOGS.mkdir(parents=True,exist_ok=True)
    check("input_integrity",inputs)
    check("release_contents",contents)
    for name in ("privacy","document","navigation","supporting","recalculation"):
        check(name,lambda name=name:getattr(Packet(ROOT,ROOT/"submission/release.pdf"),name)())
    rewards={k:float(v["passed"]) for k,v in details.items()}
    rewards["overall"]=float(all(rewards.values()))
    (LOGS/"reward.json").write_text(json.dumps(rewards,indent=2)+"\n")
    (LOGS/"details.json").write_text(json.dumps(details,indent=2)+"\n")
    print(json.dumps(rewards,indent=2))
