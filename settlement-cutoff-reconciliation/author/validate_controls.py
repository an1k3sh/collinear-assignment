"""Run controlled candidate edits after solve.sh, preserving the task inputs."""
import json
from pathlib import Path
import shutil
import subprocess

specifications = json.loads(Path("/author/controls.json").read_text())
output = Path("/logs/controls")
output.mkdir(parents=True, exist_ok=True)
results = {}
for spec in specifications:
    path = Path("/app") / spec["file"]
    original = path.read_text()
    if original.count(spec["old"]) != 1:
        raise RuntimeError("Control target must occur exactly once: " + spec["name"])
    try:
        path.write_text(original.replace(spec["old"], spec["new"]))
        result = subprocess.run(["python", "/tests/grade.py"], capture_output=True, text=True, timeout=90)
        reward = json.loads(Path("/logs/verifier/reward.json").read_text())
        destination = output / spec["name"]
        destination.mkdir(exist_ok=True)
        for filename in ("reward.json", "details.json"):
            shutil.copy2(Path("/logs/verifier") / filename, destination / filename)
        (destination / "process.log").write_text(result.stdout + result.stderr)
        results[spec["name"]] = {"expected": spec["expected"], "actual": reward["overall"],
                                 "correct": reward["overall"] == spec["expected"]}
        print(spec["name"], reward["overall"], "expected", spec["expected"], flush=True)
    finally:
        path.write_text(original)
(output / "summary.json").write_text(json.dumps(results, indent=2))
if not all(r["correct"] for r in results.values()):
    raise SystemExit(1)
