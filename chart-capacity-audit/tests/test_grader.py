import copy
import json
from pathlib import Path
import unittest

from grade import GATES, audit_checks, calculate_reward, counterfactuals
from reference import METRICS, expected, truth_observations

ROOT = Path(__file__).resolve().parents[1]


class GraderTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT/"environment/app/policy.json").read_text())
        self.truth = json.loads((ROOT/"tests/truth.json").read_text())
        self.obs = truth_observations(self.truth)

    def test_hand_calculated_totals(self):
        answer = expected(self.obs, self.policy)
        self.assertEqual(answer["fleet"]["requests"], 924000)
        self.assertEqual(answer["fleet"]["failed_requests"], 30660)
        self.assertAlmostEqual(answer["fleet"]["failure_pct"], 73/22)
        self.assertEqual(answer["regions"]["Delta"]["failed_requests"], 8580)
        self.assertEqual(answer["regions"]["Alder"]["failure_pct"], 6.4)
        self.assertEqual(answer["regions"]["Cedar"]["latency_windows"], ["W5", "W6"])
        self.assertEqual(answer["allocation"], {"Alder": 0, "Birch": 2, "Cedar": 0, "Delta": 1})
        self.assertEqual(answer["expected_benefit"], 13134)
        self.assertEqual(answer["robust_margin"], 1518)

    def test_all_admissible_reading_errors_preserve_winner(self):
        # Any valid width-limited interval containing the true value lies in
        # this larger envelope, including asymmetrically placed intervals.
        answer = expected(truth_observations(self.truth, METRICS), self.policy)
        self.assertEqual(answer["robust_margin"], 270)
        self.assertTrue(answer["robust"])
        for row in self.obs["records"]:
            if row["status"] != "normal":
                continue
            if row["window"] in answer["regions"][row["region"]]["latency_windows"]:
                v = row["p95_ms"][1]
                self.assertGreater(abs(v-self.policy["latency_trigger_ms"]), METRICS["p95_ms"])

    def test_unknown_and_maintenance_are_not_normal(self):
        answer = expected(self.obs, self.policy)
        self.assertEqual(answer["regions"]["Cedar"]["included_windows"], [f"W{i}" for i in range(1, 7)])
        self.assertEqual(answer["regions"]["Delta"]["included_windows"], [f"W{i}" for i in range(3, 9)])
        altered = copy.deepcopy(self.obs)
        for row in altered["records"]:
            if row["status"] == "maintenance":
                row["status"] = "normal"
        self.assertEqual(expected(altered, self.policy)["regions"]["Delta"]["failed_requests"], 15180)

    def test_counterfactual_boundaries(self):
        probes = list(counterfactuals(self.obs, self.policy))
        self.assertEqual(len(probes), 12)
        zero = expected(*probes[9])
        self.assertIsNone(zero["fleet"]["failure_pct"])
        self.assertEqual(sum(zero["allocation"].values()), 0)
        self.assertFalse(zero["robust"])
        one_window = expected(*probes[11])
        self.assertTrue(one_window["robust"])
        self.assertIsNone(one_window["robust_margin"])
        self.assertEqual(sum(one_window["allocation"].values()), 0)

    def test_source_evidence_and_causality(self):
        audit = json.loads((ROOT/"solution/audit.json").read_text())
        self.assertTrue(all(audit_checks(audit, self.policy).values()))
        audit["claims"][-1]["verdict"] = "correct"
        self.assertFalse(audit_checks(audit, self.policy)["D6"])
        audit["claims"][2]["evidence"] = [{"panel": "P4", "region": "Alder", "window": "W1"}]
        self.assertFalse(audit_checks(audit, self.policy)["D3"])

    def test_scoring(self):
        checks = {k: [True] for k in ("extraction", "calculations", "allocation", "claim_audit", "reproducibility")}
        checks["gates"] = dict.fromkeys(GATES, True)
        self.assertEqual(calculate_reward(checks)["overall"], 1)
        checks["extraction"] = [True]*31+[False]
        self.assertEqual(calculate_reward(checks)["overall"], .992188)
        for key in checks["gates"]:
            modified = copy.deepcopy(checks)
            modified["gates"][key] = False
            self.assertEqual(calculate_reward(modified)["overall"], 0)
            del modified["gates"][key]
            self.assertEqual(calculate_reward(modified)["overall"], 0)
        self.assertEqual(calculate_reward({})["overall"], 0)


if __name__ == "__main__":
    unittest.main()
