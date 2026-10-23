from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest

APP = Path(os.environ.get("APP_ROOT", "/app")).resolve()
sys.path.insert(0, str(APP))

from tlp.compiler import compile_case, compose, equivalent
from tlp.generator import generate
from tlp.model import Plan, Query, validate_case
from tlp.runner import replay, run_case, save_failure
from tlp.storage import execute
from reference import AGGREGATES, bag, connect, diversity, example, fixtures, reference_rows


def readonly(db):
    allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
               sqlite3.SQLITE_RECURSIVE}
    db.set_authorizer(lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY)


class TLPTests(unittest.TestCase):
    def assertBag(self, expected, actual):
        self.assertEqual(bag(expected), bag(actual))

    def test_validity_protected_files(self):
        manifest = json.loads((Path(__file__).parent / "protected.json").read_text())
        for name, expected in manifest.items():
            with self.subTest(file=name):
                self.assertEqual(hashlib.sha256((APP / name).read_bytes()).hexdigest(), expected)

    def test_validity_partition_plans(self):
        for case in fixtures():
            with self.subTest(mode=case["mode"], source=case["source"], groups=case["group_by"]):
                plan = compile_case(case)
                self.assertIsInstance(plan, Plan)
                self.assertEqual(len(plan.parts), 3)
                self.assertEqual(plan.mode, case["mode"])
                self.assertEqual(plan.group_count, len(case["group_by"]))
                # Compile once, then execute against changed data to reject answer baking.
                changed = copy.deepcopy(case)
                changed["tables"]["t"].append([9, 1, -7, "new"])
                for data in (case, changed):
                    db = connect(data)
                    try:
                        readonly(db)
                        self.assertBag(reference_rows(db, case), execute(db, plan.base))
                        for branch, query in enumerate(plan.parts):
                            actual = execute(db, query)
                            expected = reference_rows(db, case, branch, stats=True)
                            if case["mode"] == "distinct":
                                self.assertEqual(set(bag(expected)), set(bag(actual)))
                            else:
                                self.assertBag(expected, actual)
                    finally:
                        db.close()

    def test_validity_binding(self):
        case = example()
        secret = "q'; --\u0000\u2603"
        case["predicate"] = ["eq", ["col", "t", "tag"], ["lit", secret]]
        case["select"].append(["lit", secret])
        plan = compile_case(case)
        for query in (plan.base, *plan.parts):
            self.assertNotIn(secret, query.sql)
            self.assertIn(secret, query.params)
            self.assertNotIn(":memory:", query.sql)

    def test_validity_comparator(self):
        pairs = [
            ([[1], [1]], [[1]], False),
            ([[None], [1]], [[1], [None]], True),
            ([[1]], [[1.0]], False),
            ([[1]], [["1"]], False),
            ([[None]], [[""]], False),
            ([["a\u0000b", -3], ["x", None]], [["x", None], ["a\u0000b", -3]], True),
            ([[2.5]], [[2.5001]], False),
            ([[1, 2]], [[2, 1]], False),
            ([], [[None]], False),
            ([], [], True),
        ]
        for left, right, expected in pairs:
            with self.subTest(left=left, right=right):
                self.assertIs(equivalent(left, right), expected)
                self.assertIs(equivalent(right, left), expected)

    def test_validity_composition_without_database(self):
        dummy = Query("SELECT 0")
        def merge(mode, groups, states):
            return compose(Plan(dummy, (dummy, dummy, dummy), mode, groups), states)
        self.assertBag([[1], [1], [None]], merge("rows", 0, [[[1]], [[1]], [[None]]]))
        self.assertBag([[1], [None]], merge("distinct", 0, [[[1]], [[1]], [[None]]]))
        self.assertBag([[None]], merge("sum", 0, [[[None, 0]], [[None, 0]], [[None, 0]]]))
        self.assertBag([[2.5]], merge("avg", 0, [[[2, 1]], [[8, 3]], [[None, 0]]]))
        self.assertBag([["a", 3.0], [None, None], ["b", -2.0]],
                       merge("avg", 1, [[["a", 2, 1], [None, None, 0]],
                                        [["a", 7, 2]], [["b", -2, 1]]]))
        self.assertBag([[None, -7], ["z", None]],
                       merge("min", 1, [[[None, 5], ["z", None]], [], [[None, -7]]]))
        self.assertBag([[None, 5]], merge("max", 1, [[[None, 5]], [], [[None, -7]]]))
        self.assertBag([["a", 7]], merge("count", 1, [[["a", 3]], [["a", 4]], []]))
        self.assertEqual(merge("sum", 1, [[], [], []]), [])
        self.assertBag([[1], [None]], merge("group", 1, [[[1]], [[1], [None]], [[None]]]))
        self.assertBag([[4], [4], [None]], merge("having", 1, [[[4], [4]], [], [[None]]]))

    def test_validity_executor_and_detection(self):
        case = example()
        plan = compile_case(case)
        calls = []
        connections = []
        def injected(db, query):
            calls.append(query)
            connections.append(db)
            rows = execute(db, query)
            if len(calls) == 2 and rows:
                rows.append(list(rows[0]))
            return rows
        result = run_case(case, injected)
        self.assertEqual(calls, [plan.base, *plan.parts])
        self.assertIs(result["ok"], False)
        self.assertNotEqual(bag(result["expected"]), bag(result["actual"]))
        self.assertEqual(set(result), {"ok", "expected", "actual"})
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        for mode in AGGREGATES:
            aggregate = dict(case, mode=mode, select=[], value=["col", "t", "v"])
            count = 0
            def corrupt(db, query):
                nonlocal count
                count += 1
                rows = execute(db, query)
                if count == 2:
                    rows[0][0] = -999 if mode == "min" else 999
                return rows
            self.assertIs(run_case(aggregate, corrupt)["ok"], False, mode)

    def test_validity_errors(self):
        seen = []
        def broken(db, query):
            seen.append(db)
            raise sqlite3.OperationalError("controlled executor failure")
        with self.assertRaisesRegex(sqlite3.OperationalError, "controlled"):
            run_case(example(), broken)
        with self.assertRaises(sqlite3.ProgrammingError):
            seen[0].execute("SELECT 1")
        invalid = []
        for key, value in [("mode", "median"), ("source", "cross"), ("version", True),
                           ("predicate", ["raw", "DROP TABLE t"]),
                           ("select", []), ("group_by", [["col", "t", "k"]])]:
            invalid.append(dict(example(), **{key: value}))
        invalid += [dict(example(), predicate=["eq", ["col", "u", "id"], ["lit", 1]])]
        too_deep = ["eq", ["col", "t", "v"], ["lit", 0]]
        for _ in range(7):
            too_deep = ["not", too_deep]
        invalid.append(dict(example(), predicate=too_deep))
        invalid.append(dict(example(), predicate=["gt", ["agg", "sum", ["col", "t", "v"]], ["lit", 0]]))
        invalid.append(dict(example(), mode="group", group_by=[["col", "t", "k"]]))
        valid_having = dict(example(), mode="having", select=[["agg", "sum", ["col", "t", "v"]]],
                            predicate=["gt", ["agg", "sum", ["col", "t", "v"]], ["lit", 0]])
        invalid.append(dict(valid_having, predicate=["gt", ["col", "t", "v"], ["lit", 0]]))
        invalid.append(dict(valid_having, where=valid_having["predicate"]))
        invalid.append(dict(valid_having, select=[["lit", 1]]))
        invalid.append(dict(valid_having, select=[["agg", "sum", ["agg", "count", None]]]))
        for case in invalid:
            with self.assertRaises(ValueError):
                compile_case(case)
        for seed, count in [(True, 2), (0, -1), (0, 4097), (2**63, 1), (0, 1.5)]:
            with self.assertRaises(ValueError):
                generate(seed, count)

    def test_completeness_where(self):
        self.check_modes({"rows"}, filtered=False)

    def test_completeness_where_extended(self):
        self.check_modes({"rows"}, filtered=True)

    def test_completeness_distinct(self):
        self.check_modes({"distinct"})

    def test_completeness_count(self):
        self.check_modes({"count"})

    def test_completeness_sum(self):
        self.check_modes({"sum"})

    def test_completeness_avg(self):
        self.check_modes({"avg"})

    def test_completeness_min(self):
        self.check_modes({"min"})

    def test_completeness_max(self):
        self.check_modes({"max"})

    def test_completeness_group(self):
        self.check_modes({"group"})

    def test_completeness_having(self):
        self.check_modes({"having"})

    def check_modes(self, modes, filtered=None):
        for case in fixtures():
            if case["mode"] not in modes:
                continue
            if filtered is not None and (case["where"] is not None) != filtered:
                continue
            with self.subTest(case=case):
                db = connect(case)
                try:
                    expected = reference_rows(db, case)
                finally:
                    db.close()
                result = run_case(case)
                self.assertIs(result["ok"], True)
                self.assertBag(expected, result["expected"])
                self.assertBag(expected, result["actual"])

    def test_validity_group_having_witnesses(self):
        key, value = ["col", "t", "k"], ["col", "t", "v"]
        total = ["agg", "sum", value]
        case = example()
        case["tables"]["t"] = [[1, 1, 6, "a"], [2, 1, -2, "a"], [3, 2, -5, "b"],
                              [4, 3, None, "c"], [5, 4, 4, "d"], [6, None, None, None]]
        case.update(mode="having", select=[total], group_by=[key],
                    predicate=["gt", total, ["lit", 0]])
        expected = [[4], [4], [-5], [None], [None]]
        result = run_case(case)
        self.assertBag(expected, result["expected"])
        self.assertBag(expected, result["actual"])
        db = connect(case)
        try:
            plan = compile_case(case)
            for query, rows in zip(plan.parts, ([[4], [4]], [[-5]], [[None], [None]])):
                self.assertBag(rows, execute(db, query))
        finally:
            db.close()
        # A missing duplicate group is an observable mismatch, unlike set equality.
        calls = 0
        def lose_group(db, query):
            nonlocal calls
            calls += 1
            rows = execute(db, query)
            return rows[1:] if calls == 2 else rows
        self.assertIs(run_case(case, lose_group)["ok"], False)
        empty = copy.deepcopy(case)
        empty["tables"]["t"] = []
        self.assertBag([], run_case(empty)["actual"])
        empty["group_by"] = []
        self.assertBag([[None]], run_case(empty)["actual"])
        case.update(mode="group", select=[key], group_by=[key],
                    predicate=["gt", value, ["lit", 0]])
        self.assertBag([[None], [1], [2], [3], [4]], run_case(case)["actual"])

    def test_validity_reference_selfcheck(self):
        # Hand-calculated witnesses also check the independent SQL oracle itself.
        key, value = ["col", "t", "k"], ["col", "t", "v"]
        case = example()
        case["tables"]["t"] = [[1, 1, 6, "a"], [2, 1, -2, "a"],
                              [3, 2, 4, "b"], [4, 3, None, "c"]]
        case.update(mode="having", group_by=[key], select=[["agg", "sum", value]],
                    predicate=["gt", ["agg", "sum", value], ["lit", 0]])
        db = connect(case)
        try:
            self.assertBag([[4], [4], [None]], reference_rows(db, case))
            self.assertBag([[4], [4]], reference_rows(db, case, 0))
            self.assertBag([], reference_rows(db, case, 1))
            self.assertBag([[None]], reference_rows(db, case, 2))
        finally:
            db.close()

    def test_diversity_generation(self):
        global_state = random.getstate()
        first = generate(9823, 112)
        self.assertEqual(global_state, random.getstate())
        self.assertEqual(first, generate(9823, 112))
        self.assertNotEqual(first, generate(-435, 112))
        self.assertEqual(generate(0, 0), [])
        for n in (1, 7, 113, 4096):
            self.assertEqual(len(generate(34, n)), n)
        for seed in (-(2**63), 2**63 - 1):
            for case in generate(seed, 7):
                validate_case(case)

    def test_artifact_save_replay(self):
        case = example()
        result = {"ok": False, "expected": [[999]], "actual": [[888]]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "failure.json"
            save_failure(path, case, result)
            artifact = json.loads(path.read_text())
            self.assertEqual(artifact, {"version": 1, "case": case, "result": result})
            self.assertIs(replay(path)["ok"], True)
            calls = 0
            def fault(db, query):
                nonlocal calls
                calls += 1
                rows = execute(db, query)
                return rows + [[999]] if calls == 2 else rows
            self.assertIs(replay(path, fault)["ok"], False)
            with self.assertRaises(ValueError):
                save_failure(path, case, dict(result, ok=True))
            path.write_text('{"version": 1}')
            with self.assertRaises(ValueError):
                replay(path)
            with self.assertRaises(OSError):
                replay(Path(directory) / "does-not-exist.json")

    def test_artifact_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "campaign"
            env = dict(os.environ, PYTHONPATH=str(APP), PYTHONDONTWRITEBYTECODE="1")
            command = [sys.executable, "-m", "tlp", "campaign", "--seed", "19",
                       "--count", "112", "--out", str(out)]
            run = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(run.returncode, 0, run.stderr)
            summary = json.loads((out / "summary.json").read_text())
            self.assertEqual(summary, {"version": 1, "seed": 19, "requested": 112,
                                      "executed": 112, "passed": 112, "mismatches": 0})
            cases = [json.loads(line) for line in (out / "cases.jsonl").read_text().splitlines()]
            self.assertEqual(cases, generate(19, 112))
            rerun = subprocess.run(command, cwd=directory, env=env, capture_output=True, text=True, timeout=40)
            self.assertEqual(rerun.returncode, 2)
            self.assertTrue(rerun.stderr.strip())
            failure = Path(directory) / "portable.json"
            save_failure(failure, example(), {"ok": False, "expected": [], "actual": [[7]]})
            replayed = subprocess.run([sys.executable, "-m", "tlp", "replay", str(failure)],
                                     cwd=directory, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(replayed.returncode, 0, replayed.stderr)
            self.assertIs(json.loads(replayed.stdout)["ok"], True)
            failure.write_text("{")
            bad = subprocess.run([sys.executable, "-m", "tlp", "replay", str(failure)],
                                 cwd=directory, env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(bad.returncode, 2)
            self.assertTrue(bad.stderr.strip())

    def test_artifact_cli_mismatch_and_error(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, PYTHONPATH=str(APP), PYTHONDONTWRITEBYTECODE="1")
            for error in (False, True):
                out = Path(directory) / ("error" if error else "mismatch")
                script = """
import runpy, sys
from unittest.mock import patch
import tlp.runner
original = tlp.runner.run_case
def changed(case, executor=None):
    if ERROR:
        import sqlite3
        raise sqlite3.OperationalError("injected execution failure")
    result = original(case, executor)
    result["actual"] = result["actual"] + [[12345]]
    result["ok"] = False
    return result
sys.argv = ["tlp", "campaign", "--seed", "3", "--count", "3", "--out", OUT]
with patch("tlp.runner.run_case", changed):
    runpy.run_module("tlp", run_name="__main__")
""".replace("ERROR", repr(error)).replace("OUT", repr(str(out)))
                run = subprocess.run([sys.executable, "-c", script], env=env, cwd=directory,
                                     capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 2 if error else 1, run.stderr)
                if error:
                    self.assertTrue(run.stderr.strip())
                    self.assertFalse((out / "summary.json").exists())
                else:
                    summary = json.loads((out / "summary.json").read_text())
                    self.assertEqual(summary["mismatches"], 3)
                    self.assertEqual(summary["passed"], 0)
                    for i, case in enumerate(generate(3, 3)):
                        artifact = json.loads((out / f"failure-{i:06d}.json").read_text())
                        self.assertEqual(artifact["case"], case)
                        self.assertIs(artifact["result"]["ok"], False)


def make_diversity_test(category):
    def test(self):
        for seed in (0, 17, -435, 9823):
            with self.subTest(seed=seed):
                cases = generate(seed, 112)
                self.assertEqual(len(cases), 112)
                for case in cases:
                    validate_case(case)
                    # Generation gets no diversity credit for non-executable comparisons.
                    self.assertIs(run_case(case)["ok"], True)
                checks, metrics = diversity(cases)
                self.assertTrue(checks[category], json.dumps(metrics))
    return test


for category in ("modes", "sources_filters", "grouping", "operators", "shapes",
                 "partition_occupancy", "edge_data", "group_oracle", "having_oracle"):
    setattr(TLPTests, "test_diversity_" + category, make_diversity_test(category))


if __name__ == "__main__":
    unittest.main()
