"""Generate immutable-input and trial freeze manifests; never shipped to /app."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    app = ROOT / "environment" / "app"
    protected = [
        "runtime.py", "schema.sql", "demo.py", "docs/contract.md",
        "incidents/release-1.json", "incidents/release-2.json",
        "incidents/release-3.json",
        "incidents/release-4.json",
    ]
    manifest = {name: digest(app / name) for name in protected}
    (ROOT / "tests" / "immutable.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    frozen = {}
    for folder in ("environment", "tests", "solution", "steps"):
        for path in sorted((ROOT / folder).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                frozen[str(path.relative_to(ROOT))] = digest(path)
    for name in ("instruction.md", "task.toml"):
        frozen[name] = digest(ROOT / name)
    destination = ROOT / "evidence" / "frozen-inputs.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(frozen, indent=2) + "\n")
    print(f"Frozen {len(frozen)} task files")


if __name__ == "__main__":
    main()
