import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import reference as ref
from verify import CORRECTNESS, DIVERSITY, GATES, Verifier, score, verify_answer


def witness():
    c = ref.example()
    c["tables"] = {"t": [[1, 0, 8, "a"], [2, 0, -3, "b"], [3, 1, None, None]], "u": []}
    query = lambda sql: {"sql": sql, "params": []}
    plan = {"base": query("SELECT v FROM t"), "parts": [
        query("SELECT v FROM t WHERE v>0"), query("SELECT v FROM t WHERE NOT (v>0)"),
        query("SELECT v FROM t WHERE (v>0) IS NULL")]}
    return {"case": c, "plan": plan, "result":
            {"base": [[8], [-3], [None]], "combined": [[8], [-3], [None]],
             "equivalent": True, "calls": 4}}


class VerifierTests(unittest.TestCase):
    def test_score_gates_and_partial_credit(self):
        full = dict.fromkeys((*GATES, *("correctness."+k for k in CORRECTNESS),
                              *("diversity."+k for k in DIVERSITY)), True)
        metrics = {"random": {"attempted": 4, "executable": 4, "semantic": 4}}
        self.assertEqual(score(full, metrics)["overall"], 1)
        for key in (*GATES, *("correctness."+k for k in CORRECTNESS)):
            with self.subTest(key=key):
                failed = dict(full, **{key: False})
                self.assertEqual(score(failed, metrics)["overall"], 0)
                del failed[key]
                self.assertEqual(score(failed, metrics)["overall"], 0)
        self.assertEqual(score(dict(full, **{"diversity.grammar": False}), metrics)["overall"], 6/7)
        self.assertEqual(score({}, {})["overall"], 0)
        self.assertEqual(score(full, {})["input_validity_rate"], 0)

    def test_score_rate_denominators(self):
        metrics = {"random": {"attempted": 4, "executable": 3, "semantic": 2},
                   "mutations": {"attempted": 1, "executable": 1, "semantic": 1}}
        reward = score({}, metrics)
        self.assertEqual(reward["input_validity_rate"], 4/5)
        self.assertEqual(reward["semantic_validity_rate"], 3/5)
        self.assertEqual(reward["overall"], 0)

    def test_hand_calculated_reference(self):
        verify_answer(witness())

    def test_identical_queries_cannot_fake_semantics(self):
        answer = witness()
        answer["plan"]["parts"] = [answer["plan"]["base"]]*3
        with self.assertRaisesRegex(AssertionError, "query meaning"):
            verify_answer(answer)

    def test_changed_data_rejects_precomputed_answers(self):
        answer = witness()
        answer["plan"] = {
            "base": {"sql": "SELECT 8 UNION ALL SELECT -3 UNION ALL SELECT NULL", "params": []},
            "parts": [{"sql": sql, "params": []} for sql in ("SELECT 8", "SELECT -3", "SELECT NULL")]}
        verify_answer(answer, changed=False)
        with self.assertRaisesRegex(AssertionError, "changed data"):
            verify_answer(answer)

    def test_rate_denominator_schema_syntax_and_semantics(self):
        good = witness()
        invalid_schema = copy.deepcopy(good)
        invalid_schema["case"]["version"] = 99
        invalid_sql = copy.deepcopy(good)
        invalid_sql["plan"]["parts"][1]["sql"] = "not SQL"
        wrong_meaning = copy.deepcopy(good)
        wrong_meaning["plan"]["parts"][2] = {"sql": "SELECT v FROM t WHERE 0", "params": []}
        output = "\n".join(json.dumps(a) for a in (good, invalid_schema, invalid_sql, wrong_meaning))
        with tempfile.TemporaryDirectory() as directory:
            verifier = Verifier(directory, Path(directory)/"log")
            result = subprocess.CompletedProcess([], 0, stdout=output, stderr="")
            with patch.object(verifier, "command", return_value=result):
                verifier.measured_inputs([bytes([i]) for i in range(5)], "probe")
            counts = verifier.metrics["probe"]
            self.assertEqual({k: counts[k] for k in
                              ("attempted", "emitted", "schema_valid", "executable", "semantic")},
                             {"attempted": 5, "emitted": 4, "schema_valid": 3,
                              "executable": 2, "semantic": 1})
            self.assertEqual(len(counts["errors"]), 3)

    def test_mismatch_is_not_invalid_sql(self):
        answer = witness()
        answer["result"]["equivalent"] = False
        with tempfile.TemporaryDirectory() as directory:
            verifier = Verifier(directory, Path(directory)/"log")
            result = subprocess.CompletedProcess([], 0, stdout=json.dumps(answer), stderr="")
            with patch.object(verifier, "command", return_value=result):
                verifier.measured_inputs([b"a"], "probe")
            self.assertEqual(verifier.metrics["probe"]["executable"], 1)
            self.assertEqual(verifier.metrics["probe"]["semantic"], 0)


if __name__ == "__main__":
    unittest.main()
