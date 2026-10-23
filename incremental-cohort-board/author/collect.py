"""Collect reproducible evidence without copying authentication/session databases."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".json", ".jsonl", ".txt", ".log", ".md", ".py", ".sql", ".toml"}


def verify_frozen():
    expected = json.loads((ROOT / "evidence" / "frozen-inputs.json").read_text())
    mismatches = []
    for name, wanted in expected.items():
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if wanted != actual:
            mismatches.append(name)
    report = {"files_checked": len(expected), "unchanged": not mismatches,
              "mismatches": mismatches}
    (ROOT / "evidence" / "frozen-input-verification.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    if mismatches:
        raise RuntimeError(f"Frozen inputs changed: {mismatches}")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("--name")
    args = parser.parse_args()
    verify_frozen()
    source = args.job.resolve()
    target = ROOT / "evidence" / (args.name or source.name)
    target.mkdir(parents=True, exist_ok=True)
    secrets = [
        value for name, value in os.environ.items()
        if any(part in name for part in ("TOKEN", "API_KEY", "SECRET"))
        and len(value) >= 16
    ]
    copied = []
    redacted = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        if any(part in {"__pycache__", "session-state", "sessions",
                        "node_modules"} for part in relative.parts):
            continue
        if path.name.startswith("session-store"):
            continue
        eligible = (
            len(relative.parts) == 1
            or "verifier" in relative.parts
            or "artifacts" in relative.parts
            or path.name in {
                "trajectory.json", "copilot-cli.jsonl", "copilot-cli.txt",
                "oracle.txt", "trial.log", "result.json", "config.json",
            }
        )
        if not eligible or path.suffix in {".pyc", ".db"}:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_bytes()
        if path.suffix in TEXT_SUFFIXES:
            for secret in secrets:
                encoded = secret.encode()
                if encoded in content:
                    content = content.replace(encoded, b"[REDACTED_CREDENTIAL]")
                    redacted.append(str(relative))
        destination.write_bytes(content)
        copied.append({
            "path": str(relative),
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        })
    index = {
        "source_job": source.name, "files": copied,
        "credential_redactions": sorted(set(redacted)),
        "excluded": ["authentication/session databases", "CLI session-state",
                     "node_modules", "Python bytecode"],
    }
    (target / "evidence-index.json").write_text(json.dumps(index, indent=2) + "\n")
    print(f"Collected {len(copied)} files from {source.name}; "
          f"{len(redacted)} credential redactions")


if __name__ == "__main__":
    main()
