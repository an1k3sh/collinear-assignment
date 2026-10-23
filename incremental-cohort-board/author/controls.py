"""Run valid alternatives and plausible faulty implementations in fresh containers."""
import argparse
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(source, old, new):
    if source.count(old) != 1:
        raise ValueError(f"Control edit is not unique: {old!r}")
    return source.replace(old, new)


def variants(source):
    return {
        "valid-read-only-schema-introspection": (
            replace(
                source,
                "def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:",
                "def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:\n"
                "    db.execute('PRAGMA table_info(orders)').fetchall()\n"
                "    db.execute('PRAGMA foreign_keys').fetchall()"
            ), True
        ),
        "valid-auxiliary-schema-evolution": (
            replace(
                source,
                "def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:",
                "def bootstrap(db: sqlite3.Connection, modes: Sequence[str]) -> None:\n"
                "    db.execute('CREATE TABLE IF NOT EXISTS aux_probe (x INTEGER)')\n"
                "    columns = db.execute('PRAGMA table_info(aux_probe)').fetchall()\n"
                "    if len(columns) == 1:\n"
                "        db.execute('ALTER TABLE aux_probe ADD COLUMN y INTEGER')"
            ), True
        ),
        "valid-reverse-order-unescaped-keys": (
            replace(source.replace(
                "for account in affected:",
                "for account in sorted(affected, reverse=True):"
            ), "ensure_ascii=True", "ensure_ascii=False"), True
        ),
        "full-rebuild-on-every-batch": (
            source[:source.index("\ndef maintain(")] + """
def maintain(db, modes, changes):
    bootstrap(db, modes)
""", False
        ),
        "all-null-sums-become-zero": (
            source.replace("total if priced else None", "total"), False
        ),
        "distinct-account-count-is-row-count": (
            replace(source, "(*key, count, priced, total if priced else None, accounts,",
                    "(*key, count, priced, total if priced else None, count,"),
            False,
        ),
        "ignores-before-images": (
            replace(source,
                    '(change["before"], change["after"])',
                    '(change["after"],)'), False
        ),
        "ignores-rate-only-corrections": (
            replace(source, "for segment in segments:",
                    "for segment in ():"),
            False,
        ),
        "null-safe-join-instead-of-sql-equality": (
            source.replace("ON t.segment=r.segment", "ON t.segment IS r.segment"),
            False,
        ),
        "deduplicates-source-tag-bag": (
            source.replace(
                "tags t ON o.account=t.account",
                "(SELECT DISTINCT account,segment FROM tags) t "
                "ON o.account=t.account"
            ), False
        ),
        "does-not-retract-old-extrema": (
            replace(
                source,
                'db.execute("DELETE FROM aux_parts WHERE account=?", (account,))',
                'db.execute("DELETE FROM aux_parts WHERE account=? AND 0", (account,))'
            ), False
        ),
        "counts-accounts-instead-of-households": (
            replace(
                source,
                "return int(new > 0) - int(old > 0)",
                "return change"
            ), False
        ),
        "monotone-alias-components-never-split": (
            replace(
                source,
                'representative = min(component)\n        db.executemany(\n'
                '            "INSERT OR REPLACE INTO aux_identity',
                'representative = min(old[account] for account in component)\n'
                '        db.executemany(\n'
                '            "INSERT OR REPLACE INTO aux_identity'
            ), False
        ),
        "ignores-alias-only-updates": (
            replace(
                source,
                'elif change["table"] == "links" and "household" in modes:',
                'elif change["table"] == "links" and False:'
            ), False
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="incremental-cohort-board:author")
    args = parser.parse_args()
    source = (ROOT / "solution" / "maintainer.py").read_text()
    controls = variants(source)
    output = ROOT / "evidence" / "controls"
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    with tempfile.TemporaryDirectory(prefix="cohort-controls-") as folder:
        for name, (code, should_pass) in controls.items():
            variant = Path(folder) / f"{name}.py"
            variant.write_text(code)
            logs = output / name
            logs.mkdir(exist_ok=True)
            command = [
                "docker", "run", "--rm", "--network", "none",
                "-v", f"{ROOT / 'tests'}:/tests:ro",
                "-v", f"{ROOT / 'solution'}:/solution:ro",
                "-v", f"{variant}:/variant.py:ro",
                "-v", f"{logs}:/logs/verifier",
                args.image, "bash", "-c",
                "printf '4\\n' > /app/release.txt; "
                "bash /solution/solve.sh >/tmp/oracle.txt 2>&1 && "
                "cp /variant.py /app/maintainer.py && bash /tests/test.sh",
            ]
            run = subprocess.run(command, text=True, capture_output=True, timeout=180)
            (logs / "execution.txt").write_text(run.stdout + run.stderr)
            reward_path = logs / "reward.json"
            if not reward_path.exists():
                raise RuntimeError(f"Control infrastructure failed: {name}")
            reward = json.loads(reward_path.read_text())
            passed = reward["overall"] == 1.0
            results[name] = {
                "expected_pass": should_pass, "actual_pass": passed,
                "correctly_classified": passed == should_pass,
                "exit_code": run.returncode, "reward": reward,
            }
            print(name, results[name], flush=True)
    (output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    return int(not all(row["correctly_classified"] for row in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
