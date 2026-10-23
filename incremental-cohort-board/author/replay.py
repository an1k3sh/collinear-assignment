"""Regrade unchanged captured submissions after a verifier-only fairness correction."""
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--image", default="incremental-cohort-board:author")
    args = parser.parse_args()
    job = args.job.resolve()
    output = ROOT / "evidence" / f"{job.name}-final-verifier-replay"
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    for release in range(1, 5):
        candidates = list(job.glob(
            f"*/steps/release-{release}/artifacts/**/maintainer.py"
        ))
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one captured source for release {release}")
        app = candidates[0].parent
        logs = output / f"release-{release}"
        logs.mkdir(exist_ok=True)
        command = [
            "docker", "run", "--rm", "--network", "none",
            "-e", f"BOARD_RELEASE={release}",
            "-v", f"{ROOT / 'tests'}:/tests:ro",
            "-v", f"{app}:/captured:ro",
            "-v", f"{logs}:/logs/verifier",
            args.image, "bash", "-c",
            "cp -a /captured/. /app/ && bash /tests/test.sh",
        ]
        run = subprocess.run(command, text=True, capture_output=True, timeout=240)
        (logs / "execution.txt").write_text(run.stdout + run.stderr)
        reward = logs / "reward.json"
        if not reward.is_file():
            raise RuntimeError(f"Replay infrastructure failed: release {release}")
        result = json.loads(reward.read_text())
        results[f"release-{release}"] = {
            "reward": result, "exit_code": run.returncode,
            "candidate_modified": False,
        }
        print(release, results[f"release-{release}"], flush=True)
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return int(any(
        result["reward"]["overall"] != 1 for result in results.values()
    ))


if __name__ == "__main__":
    raise SystemExit(main())
