"""Post-trial fairness audit; does not change the frozen acceptance suite."""
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, "/tests")
from carrier_checks import SEND, fixture
from durable_checks import SENTINEL, diagnostic
from test_semantics import equal

with fixture() as f:
    f.saved.write_bytes(SENTINEL)
    diagnostic(f.run("proc main(){"+SEND+"}", save=True,
                     output=f.root/"missing"/"result.json"), "IO", 7)
    preflight = dict(accepted_keys=sorted(f.accepted()), attempts=f.attempts())
    equal(f.output.read_bytes().hex(), SENTINEL.hex(), "preflight output atomicity")
    equal(f.saved.read_bytes().hex(), SENTINEL.hex(), "preflight checkpoint atomicity")

wrapper = '''
import errno
import os
from pathlib import Path
import runpy
import sys
sys.argv = ["stockroom", *sys.argv[1:]]
target = Path(sys.argv[sys.argv.index("--out")+1]).resolve()
replace = os.replace
def fail_result_replace(source, destination, *args, **kwargs):
    if Path(destination).resolve() == target:
        raise OSError(errno.EIO, "author-injected late publication failure")
    return replace(source, destination, *args, **kwargs)
os.replace = fail_result_replace
runpy.run_module("stockroom", run_name="__main__")
'''
with fixture() as f:
    f.program.write_text("proc main(){"+SEND+"}")
    f.saved.write_bytes(SENTINEL)
    process = subprocess.run(
        [sys.executable, "-c", wrapper, str(f.program),
         "--inventory", str(f.incoming), "--out", str(f.output),
         "--checkpoint", str(f.saved), "--carrier", str(f.database)],
        cwd="/app", capture_output=True, text=True, timeout=15)
    diagnostic(process, "IO", 7)
    equal(f.output.read_bytes().hex(), SENTINEL.hex(), "late failure preserves output")
    equal(f.saved.read_bytes().hex(), SENTINEL.hex(), "late failure preserves checkpoint")
    equal(sorted(f.accepted()), ["x"], "actual publication failure retains prior acceptance")
    equal(f.attempts(), [("x","accepted")], "actual publication failure retains attempt audit")
    late = dict(passed=True,accepted_keys=sorted(f.accepted()),attempts=f.attempts())

result = dict(missing_parent_observation=preflight, injected_late_publication_failure=late)
Path("/logs/verifier/publication-audit.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result))
