"""Post-run diagnostics: measure emitted cases, not candidate success claims."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import sqlite3
import sys
from typing import Callable

from reference import connect

SEEDS = (0, 17, -435, 9823)
CASE_ERRORS = (ValueError, TypeError, AttributeError, KeyError, IndexError,
               RuntimeError, sqlite3.Error)


def measure(generator: Callable, compiler: Callable, validator: Callable,
            seeds: tuple[int, ...] = SEEDS, count: int = 112) -> dict:
    totals = {"requested_cases": count * len(seeds), "emitted_cases": 0,
              "schema_valid_cases": 0, "executable_cases": 0}
    runs = []
    for seed in seeds:
        run = {"seed": seed, "requested_cases": count, "emitted_cases": 0,
               "schema_valid_cases": 0, "executable_cases": 0,
               "error_count": 0, "errors": []}

        def record(stage: str, index: int | None, error: Exception) -> None:
            run["error_count"] += 1
            if len(run["errors"]) < 20:
                run["errors"].append({"stage": stage, "index": index,
                                      "type": type(error).__name__, "message": str(error)})

        try:
            cases = generator(seed, count)
            if not isinstance(cases, list):
                raise TypeError("generate must return a list")
        except CASE_ERRORS as error:
            record("generation", None, error)
            runs.append(run)
            continue
        run["emitted_cases"] = len(cases)
        for index, case in enumerate(cases):
            try:
                validator(case)
            except CASE_ERRORS as error:
                record("schema", index, error)
                continue
            run["schema_valid_cases"] += 1
            connection = None
            try:
                plan = compiler(case)
                if len(plan.parts) != 3:
                    raise ValueError("plan must have exactly three partitions")
                connection = connect(case)
                permitted = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ,
                             sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
                connection.set_authorizer(
                    lambda action, *_: sqlite3.SQLITE_OK if action in permitted else sqlite3.SQLITE_DENY
                )
                for query in (plan.base, *plan.parts):
                    connection.execute(query.sql, query.params).fetchall()
                run["executable_cases"] += 1
            except CASE_ERRORS as error:
                record("execution", index, error)
            finally:
                if connection is not None:
                    connection.close()
        for field in ("emitted_cases", "schema_valid_cases", "executable_cases"):
            totals[field] += run[field]
        runs.append(run)
    emitted = totals["emitted_cases"]
    return {
        "version": 1, **totals,
        "schema_validity_rate": totals["schema_valid_cases"] / emitted if emitted else 0.0,
        "input_validity_rate": totals["executable_cases"] / emitted if emitted else 0.0,
        "exact_emission_count": all(r["emitted_cases"] == r["requested_cases"] for r in runs),
        "error_count": sum(r["error_count"] for r in runs),
        "runs": runs,
        "runtime": {"python": platform.python_version(), "sqlite": sqlite3.sqlite_version},
        "scope": "Schema-valid and executable inputs; no result-equivalence requirement.",
    }


def measure_candidate() -> dict:
    app = Path(os.environ.get("APP_ROOT", "/app")).resolve()
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    from tlp.compiler import compile_case
    from tlp.generator import generate
    from tlp.model import validate_case
    return measure(generate, compile_case, validate_case)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = measure_candidate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}))


if __name__ == "__main__":
    main()
