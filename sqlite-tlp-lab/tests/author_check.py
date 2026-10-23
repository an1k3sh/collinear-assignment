"""Run each candidate in an isolated workspace; mutations test the grader."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

TASK = Path(__file__).resolve().parents[1]

MUTATIONS = {
    "set-not-bag": ("compiler.py", '''
def equivalent(expected, actual):
    return set(map(typed_row, expected)) == set(map(typed_row, actual))
'''),
    "omit-unknown": ("compiler.py", '''
_original_compile = compile_case
def compile_case(case):
    p = _original_compile(case)
    return Plan(p.base, (p.parts[0], p.parts[1], p.parts[1]), p.mode, p.group_count)
'''),
    "average-of-averages": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    result = _original_compose(plan, partitions)
    if plan.mode == "avg" and plan.group_count == 0:
        means = [row[0] / row[1] for part in partitions for row in part if row[1]]
        return [[sum(means) / len(means) if means else None]]
    return result
'''),
    "null-sum-as-zero": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    result = _original_compose(plan, partitions)
    if plan.mode == "sum":
        return [row[:-1] + [0 if row[-1] is None else row[-1]] for row in result]
    return result
'''),
    "left-as-inner": ("compiler.py", '''
_original_compile = compile_case
def compile_case(case):
    changed = dict(case)
    if changed["source"] == "left":
        changed["source"] = "inner"
    return _original_compile(changed)
'''),
    "ignore-existing-filter": ("compiler.py", '''
_original_compile = compile_case
def compile_case(case):
    return _original_compile(dict(case, where=None))
'''),
    "distinct-per-partition-only": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    if plan.mode == "distinct":
        return [row for part in partitions
                for row in {typed_row(r): r for r in part}.values()]
    return _original_compose(plan, partitions)
'''),
    "drop-partition-local-groups": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    result = _original_compose(plan, partitions)
    if plan.group_count:
        keys = {typed_row(row[:plan.group_count]) for row in partitions[0]}
        return [row for row in result if typed_row(row[:plan.group_count]) in keys]
    return result
'''),
    "always-success": ("runner.py", '''
_original_run = run_case
def run_case(case, executor=None):
    result = _original_run(case, executor)
    result["ok"] = True
    return result
'''),
    "ignore-executor": ("runner.py", '''
_original_run = run_case
def run_case(case, executor=None):
    return _original_run(case)
'''),
    "vacuous-generator": ("generator.py", '''
_original_generate = generate
def generate(seed, count):
    cases = _original_generate(seed, count)
    for case in cases:
        case["tables"] = {"t": [], "u": []}
    return cases
'''),
    "replay-recorded-claim": ("runner.py", '''
def replay(path, executor=None):
    return json.loads(Path(path).read_text())["result"]
'''),
    "group-bag-union": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    if plan.mode == "group":
        return [row for part in partitions for row in part]
    return _original_compose(plan, partitions)
'''),
    "having-set-union": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    result = _original_compose(plan, partitions)
    if plan.mode == "having":
        return list({typed_row(row): row for row in result}.values())
    return result
'''),
    "having-missing-unknown": ("compiler.py", '''
_original_compile = compile_case
def compile_case(case):
    plan = _original_compile(case)
    if plan.mode == "having":
        missing = Query("SELECT * FROM (" + plan.parts[2].sql + ") WHERE 0",
                        plan.parts[2].params)
        return Plan(plan.base, (plan.parts[0], plan.parts[1], missing),
                    plan.mode, plan.group_count)
    return plan
'''),
    "having-drop-empty-group": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    result = _original_compose(plan, partitions)
    if plan.mode == "having" and plan.group_count == 0 and result == [[None]]:
        return []
    return result
'''),
    "having-row-stage-partition": ("compiler.py", '''
_original_compile = compile_case
def compile_case(case):
    plan = _original_compile(case)
    if plan.mode != "having":
        return plan
    # Deliberately apply a simple SUM predicate to rows before aggregation.
    pred = case["predicate"]
    if pred[0] == "gt" and pred[1][0] == "agg" and pred[1][1] == "sum":
        parts = []
        for branch in range(3):
            params = []
            columns = [expression_sql(e, params) for e in case["select"]]
            source = '"t"'
            if case["source"] != "single":
                source += (' LEFT JOIN ' if case["source"] == "left" else ' INNER JOIN ')
                source += '"u" ON "t"."k" = "u"."k"'
            sql = "SELECT " + ", ".join(columns) + " FROM " + source
            conditions = []
            if case["where"] is not None:
                conditions.append(expression_sql(case["where"], params))
            row_pred = expression_sql(["gt", pred[1][2], pred[2]], params)
            conditions.append([row_pred, "NOT ("+row_pred+")",
                               "("+row_pred+") IS NULL"][branch])
            sql += " WHERE " + " AND ".join("("+c+")" for c in conditions)
            if case["group_by"]:
                sql += " GROUP BY " + ", ".join(expression_sql(e, params)
                                                for e in case["group_by"])
            parts.append(Query(sql, tuple(params)))
        return Plan(plan.base, tuple(parts), plan.mode, plan.group_count)
    return plan
'''),
}

POSITIVES = {
    "alternative-sql-wrapper": ("compiler.py", '''
_original_compile = compile_case
def compile_case(case):
    p = _original_compile(case)
    def wrap(query):
        return Query("SELECT * FROM (" + query.sql + ") AS equivalent_query", query.params)
    return Plan(wrap(p.base), tuple(wrap(q) for q in p.parts), p.mode, p.group_count)
'''),
    "alternative-row-order": ("compiler.py", '''
_original_compose = compose
def compose(plan, partitions):
    return list(reversed(_original_compose(plan, partitions)))
'''),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", choices=["baseline", "oracle", *POSITIVES, *MUTATIONS], nargs="+")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name in args.only or ["baseline", "oracle", *POSITIVES, *MUTATIONS]:
        evidence = args.out / name
        evidence.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="tlp-author-") as directory:
            app = Path(directory) / "app"
            shutil.copytree(TASK / "environment" / "app", app)
            if name != "baseline":
                for module in ("compiler.py", "runner.py", "generator.py", "__main__.py"):
                    shutil.copyfile(TASK / "solution" / module, app / "tlp" / module)
            if name in MUTATIONS or name in POSITIVES:
                module, addition = {**MUTATIONS, **POSITIVES}[name]
                with (app / "tlp" / module).open("a") as stream:
                    stream.write(addition)
            env = dict(os.environ, APP_ROOT=str(app), VERIFIER_LOG=str(evidence.resolve()),
                       PYTHONDONTWRITEBYTECODE="1")
            with (evidence / "verifier.log").open("w") as log:
                result = subprocess.run([sys.executable, str(TASK / "tests" / "grade.py")],
                                        cwd=app, env=env, stdout=log, stderr=subprocess.STDOUT,
                                        timeout=150)
            reward = json.loads((evidence / "reward.json").read_text())
            summary[name] = {"exit_code": result.returncode, "reward": reward}
            print(name, json.dumps(reward), flush=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if all(
        record["exit_code"] == 0 and record["reward"]["overall"] == 1.0
        if name == "oracle" or name in POSITIVES
        else record["exit_code"] != 0 and record["reward"]["overall"] == 0.0
        for name, record in summary.items()
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
