import copy
from types import SimpleNamespace
import unittest

from input_validity import measure
from reference import example


def query(sql):
    return SimpleNamespace(sql=sql, params=())


def plan(base="SELECT 1", partition="SELECT 1"):
    return SimpleNamespace(base=query(base), parts=[query(partition)] * 3)


def validate(case):
    if case.get("invalid"):
        raise ValueError("controlled invalid AST")


class InputValidityTests(unittest.TestCase):
    def test_mismatch_is_still_executable(self):
        report = measure(lambda *_: [example()], lambda _: plan("SELECT 1", "SELECT 2"),
                         validate, seeds=(1,), count=1)
        self.assertEqual(report["input_validity_rate"], 1.0)
        self.assertEqual(report["executable_cases"], 1)
        self.assertTrue(report["exact_emission_count"])

    def test_schema_and_execution_failures_are_distinct(self):
        bad_schema = dict(example(), invalid=True)
        bad_sql = dict(example(), bad_sql=True)
        cases = [example(), bad_schema, bad_sql, copy.deepcopy(example())]
        report = measure(lambda *_: cases,
                         lambda c: plan("SELECT nonexistent" if c.get("bad_sql") else "SELECT 1"),
                         validate, seeds=(1,), count=4)
        self.assertEqual(report["emitted_cases"], 4)
        self.assertEqual(report["schema_valid_cases"], 3)
        self.assertEqual(report["executable_cases"], 2)
        self.assertEqual(report["input_validity_rate"], 0.5)
        self.assertEqual(report["error_count"], 2)
        self.assertEqual([e["stage"] for e in report["runs"][0]["errors"]],
                         ["schema", "execution"])

    def test_missing_output_does_not_claim_complete_generation(self):
        report = measure(lambda *_: [example()], lambda _: plan(), validate, seeds=(1,), count=4)
        self.assertEqual(report["input_validity_rate"], 1.0)
        self.assertFalse(report["exact_emission_count"])
        self.assertEqual(report["requested_cases"], 4)
        self.assertEqual(report["emitted_cases"], 1)
        empty = measure(lambda *_: [], lambda _: plan(), validate, seeds=(1,), count=4)
        self.assertEqual(empty["input_validity_rate"], 0.0)

    def test_generator_error_is_recorded(self):
        def broken(*_):
            raise ValueError("controlled generator failure")
        report = measure(broken, lambda _: plan(), validate, seeds=(1,), count=4)
        self.assertEqual(report["input_validity_rate"], 0.0)
        self.assertEqual(report["error_count"], 1)
        self.assertEqual(report["runs"][0]["errors"][0]["stage"], "generation")

    def test_all_queries_are_executed_and_writes_rejected(self):
        for sql in ("SELECT nonexistent", "DELETE FROM t"):
            report = measure(lambda *_: [example()], lambda _: plan(partition=sql),
                             validate, seeds=(1,), count=1)
            self.assertEqual(report["executable_cases"], 0)
            self.assertEqual(report["error_count"], 1)


if __name__ == "__main__":
    unittest.main()
