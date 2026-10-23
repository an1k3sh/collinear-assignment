from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .generator import generate
from .runner import replay, run_case, save_failure


def campaign(seed: int, count: int, out: Path) -> int:
    cases = generate(seed, count)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise ValueError("output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    mismatches = 0
    with (out / "cases.jsonl").open("w", encoding="utf-8") as stream:
        for index, case in enumerate(cases):
            stream.write(json.dumps(case, ensure_ascii=True) + "\n")
            result = run_case(case)
            if not result["ok"]:
                mismatches += 1
                save_failure(out / f"failure-{index:06d}.json", case, result)
    summary = {"version": 1, "seed": seed, "requested": count, "executed": len(cases),
               "passed": len(cases) - mismatches, "mismatches": mismatches}
    (out / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 1 if mismatches else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("campaign")
    run.add_argument("--seed", type=int, required=True)
    run.add_argument("--count", type=int, required=True)
    run.add_argument("--out", type=Path, required=True)
    again = commands.add_parser("replay")
    again.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "campaign":
            return campaign(args.seed, args.count, args.out)
        result = replay(args.path)
        print(json.dumps(result))
        return 0 if result["ok"] else 1
    except (ValueError, OSError, sqlite3.Error) as error:
        print(f"tlp: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
