"""Export whitelisted Harbor evidence, without environment/config credentials."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("label")
    args = parser.parse_args()
    trials = [p for p in args.job.iterdir() if p.is_dir() and (p / "result.json").exists()]
    if len(trials) != 1:
        raise ValueError(f"Expected exactly one completed trial, got {len(trials)}")
    trial = trials[0]
    result = json.loads((trial / "result.json").read_text())
    agent = result["config"]["agent"]
    summary = {k: result.get(k) for k in [
        "task_name", "task_checksum", "trial_name", "agent_info",
        "verifier_result", "exception_info", "started_at", "finished_at", "step_results"]}
    summary["requested_agent"] = {k: agent.get(k) for k in [
        "name", "model_name", "kwargs", "resume_trajectory"]}
    target = ROOT / "evidence" / args.label
    target.mkdir(parents=True, exist_ok=True)
    (target / "trial-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    secrets = [v for k, v in os.environ.items()
               if any(s in k for s in ["TOKEN", "API_KEY", "SECRET"]) and len(v) >= 8]
    for step in result.get("step_results", []):
        name = step["step_name"]
        for relative in ["verifier/checks.json", "verifier/reward.json",
                         "verifier/test-stdout.txt", "agent/trajectory.json",
                         "agent/copilot-cli.jsonl", "agent/claude-code.txt"]:
            source = trial / "steps" / name / relative
            if source.is_file():
                text = source.read_text()
                for secret in secrets:
                    text = text.replace(secret, "[REDACTED]")
                out = target / name / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text)
        for relative in ["refresh.py", "plan.py", "output/settlement.xlsx", "output/claim-plan.xlsx",
                         "output/reconciliation.json", "output/plan.json"]:
            source = trial / "steps" / name / "artifacts" / "workspace" / relative
            if source.is_file():
                out = target / name / "deliverables" / relative
                out.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix == ".xlsx":
                    out.write_bytes(source.read_bytes())
                else:
                    text = source.read_text()
                    for secret in secrets:
                        text = text.replace(secret, "[REDACTED]")
                    out.write_text(text)
    print(f"Exported {args.label} evidence to {target}")


if __name__ == "__main__":
    main()
