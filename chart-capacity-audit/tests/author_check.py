"""Full acceptance/rejection controls; keep outside the agent image."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    summary = {}
    cases = [
        "oracle", "approximate-readings", "reordered-records",
        "baseline", "wrong-axis", "maintenance-included", "unknown-as-zero",
        "unweighted-fleet", "per-minute-not-total", "wrong-allocation",
        "causal-overclaim", "static-program", "false-robustness", "wrong-citation",
    ]
    for name in cases:
        with tempfile.TemporaryDirectory(prefix="chart-control-") as temporary:
            app = Path(temporary)/"app"
            shutil.copytree(ROOT/"environment/app", app)
            sub = app/"submission"
            sub.mkdir()
            if name != "baseline":
                for filename in ("observations.json", "analyze.py", "audit.json", "audit.md"):
                    shutil.copyfile(ROOT/"solution"/filename, sub/filename)
                obs = json.loads((sub/"observations.json").read_text())
                audit = json.loads((sub/"audit.json").read_text())
                if name == "approximate-readings":
                    for row in obs["records"]:
                        if row["status"] != "unknown":
                            row["rate"][1] += 20
                            row["failure_pct"][1] += .05
                            row["p95_ms"][1] += 1
                if name == "reordered-records":
                    obs["records"].reverse()
                if name == "wrong-axis":
                    for row in obs["records"]:
                        if row["region"] == "Alder":
                            row["rate"] = [v*5 for v in row["rate"]]
                if name == "maintenance-included":
                    for row in obs["records"]:
                        if row["status"] == "maintenance":
                            row["status"] = "normal"
                if name == "unknown-as-zero":
                    for row in obs["records"]:
                        if row["status"] == "unknown":
                            row["status"] = "normal"
                            for metric in ("rate", "failure_pct", "p95_ms"):
                                row[metric] = [0, 0, 0]
                if name == "wrong-citation":
                    obs["records"][0]["sources"]["rate"] = "P2"
                if name == "causal-overclaim":
                    audit["claims"][-1]["verdict"] = "correct"
                (sub/"observations.json").write_text(json.dumps(obs))
                (sub/"audit.json").write_text(json.dumps(audit))
                result = subprocess.run([sys.executable, str(sub/"analyze.py"),
                    "--observations", str(sub/"observations.json"), "--policy", str(app/"policy.json"),
                    "--out", str(sub/"analysis.json")], capture_output=True, text=True)
                assert result.returncode == 0, (name, result.stderr)
                analysis = json.loads((sub/"analysis.json").read_text())
                if name == "unweighted-fleet":
                    analysis["fleet"]["failure_pct"] = sum(r["failure_pct"] for r in analysis["regions"].values())/4
                if name == "per-minute-not-total":
                    for row in [*analysis["regions"].values(), analysis["fleet"]]:
                        row["requests"] /= 30
                        row["failed_requests"] /= 30
                if name == "wrong-allocation":
                    analysis["allocation"] = {"Alder": 2, "Birch": 0, "Cedar": 0, "Delta": 1}
                if name == "false-robustness":
                    analysis["robust_margin"] = 99999
                (sub/"analysis.json").write_text(json.dumps(analysis))
                if name == "static-program":
                    (sub/"analyze.py").write_text(
                        "import json,sys\nfrom pathlib import Path\n"
                        f"answer = json.loads({json.dumps(analysis)!r})\n"
                        "Path(sys.argv[sys.argv.index('--out')+1]).write_text(json.dumps(answer))\n")
            log = out/name
            env = dict(os.environ, APP_ROOT=str(app), VERIFIER_LOG=str(log), PYTHONDONTWRITEBYTECODE="1")
            run = subprocess.run([sys.executable, str(ROOT/"tests/grade.py")],
                                 env=env, capture_output=True, text=True, timeout=120)
            (out/(name+".log")).write_text(run.stdout+run.stderr)
            reward = json.loads((log/"reward.json").read_text())
            wanted = 1 if name in ("oracle", "approximate-readings", "reordered-records") else 0
            summary[name] = {"reward": reward, "expected": wanted, "exit": run.returncode}
            (out/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
            print(name, json.dumps(reward), flush=True)
            assert reward["overall"] == wanted and (run.returncode == 0) == bool(wanted), name
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
