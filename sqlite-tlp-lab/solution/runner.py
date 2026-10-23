from __future__ import annotations

import json
from pathlib import Path

from .compiler import compile_case, compose, equivalent
from .model import Case, Executor, validate_case
from .storage import execute, open_database


def run_case(case: Case, executor: Executor | None = None) -> dict:
    plan = compile_case(case)
    connection = open_database(case)
    try:
        execute_query = execute if executor is None else executor
        expected = execute_query(connection, plan.base)
        partitions = [execute_query(connection, query) for query in plan.parts]
        actual = compose(plan, partitions)
        return {"ok": equivalent(expected, actual), "expected": expected, "actual": actual}
    finally:
        connection.close()


def save_failure(path: str | Path, case: Case, result: dict) -> None:
    validate_case(case)
    if set(result) != {"ok", "expected", "actual"} or result["ok"] is not False:
        raise ValueError("only mismatches can be saved")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"version": 1, "case": case, "result": result},
                                ensure_ascii=True) + "\n", encoding="utf-8")


def replay(path: str | Path, executor: Executor | None = None) -> dict:
    artifact = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(artifact, dict) or set(artifact) != {"version", "case", "result"}:
        raise ValueError("invalid artifact shape")
    if type(artifact["version"]) is not int or artifact["version"] != 1:
        raise ValueError("invalid artifact version")
    result = artifact["result"]
    if not isinstance(result, dict) or set(result) != {"ok", "expected", "actual"}:
        raise ValueError("invalid recorded result")
    if type(result["ok"]) is not bool or not all(isinstance(result[k], list) for k in ("expected", "actual")):
        raise ValueError("invalid recorded result fields")
    return run_case(artifact["case"], executor)
