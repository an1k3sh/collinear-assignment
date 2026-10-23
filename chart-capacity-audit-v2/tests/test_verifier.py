import copy
import json
from pathlib import Path
import unittest

from grade import COMPONENTS, GATES, extraction, probes, score
from reference import expected, intervals_from_truth, optimize, reading_index

ROOT = Path(__file__).resolve().parents[1]


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.truth = json.loads((ROOT/"tests/truth.json").read_text())
        self.readings = intervals_from_truth(self.truth, .25)
        app = ROOT/"environment/app"
        self.manifest, self.operations, self.planning = [
            json.loads((app/name).read_text()) for name in
            ("export-manifest.json","operations.json","planning.json")]

    def result(self, readings=None):
        return expected(readings or self.readings, self.manifest, self.operations, self.planning)

    def test_hand_calculated_workload(self):
        result = self.result()
        self.assertEqual(result["targets"]["AS"]["errors"], 10000)
        self.assertEqual(result["targets"]["BI"]["errors"], 16000)
        self.assertEqual(result["targets"]["DS"]["errors"], 11000)
        self.assertEqual(result["targets"]["DI"]["errors"], 5500)
        self.assertEqual(result["targets"]["DS"]["usable_windows"], ["W1","W3","W4"])
        self.assertEqual(result["targets"]["DS"]["requests"], 880000)
        self.assertEqual(result["targets"]["BI"]["requests"], 960000)

    def test_reset_and_missing_are_distinct(self):
        rows = {(r["target"],r["window"]):r for r in self.result()["intervals"]}
        self.assertEqual(rows["DS","W2"]["reason"], "missing_traffic")
        self.assertIsNone(rows["DS","W2"]["errors"])
        self.assertEqual(rows["DS","W3"]["reason"], "usable")
        self.assertEqual(rows["DS","W3"]["errors"][1], 4000)
        self.assertEqual(rows["BI","W2"]["requests"][1], 320000)
        self.assertEqual(rows["BI","W2"]["errors"][1], 4500)
        self.assertEqual(rows["DI","W2"]["errors"][1], 9000)
        self.assertFalse(rows["DI","W2"]["latency_included"])

    def test_pooling_not_voting(self):
        cs = self.result()["targets"]["CS"]
        self.assertEqual(cs["samples"], 13000)
        self.assertAlmostEqual(cs["slow_fraction"], 310/13000)
        self.assertEqual(cs["p95_bin"], "(100,300]")
        self.assertFalse(cs["latency_eligible"])
        ci = self.result()["targets"]["CI"]
        self.assertTrue(ci["latency_eligible"])
        self.assertFalse(ci["rollout_eligible"])
        self.assertEqual(ci["block_reason"], "region_freeze")

    def test_inventory_and_units(self):
        result = self.result()
        self.assertEqual(result["inventory"]["rejected"], ["C2.r1"])
        self.assertEqual(result["inventory"]["by_target"]["BI"]["counters"], "C2.r2")
        self.assertEqual(result["targets"]["AS"]["requests"], 600000)
        self.assertEqual(result["plan"]["credits"], 14)
        self.assertEqual(result["plan"]["power"], 8)
        self.assertEqual(result["plan"]["objective"], 26320)
        self.assertEqual(result["plan"]["residual_risk"], 90530)
        self.assertEqual(result["scenarios"][1]["objective"], 31820)

    def test_widest_visual_envelope(self):
        exact = self.result(intervals_from_truth(self.truth,0))
        self.assertEqual(exact["plan"]["robust_margin"],1220)
        full = self.result(intervals_from_truth(self.truth, 1))
        self.assertTrue(full["plan"]["robust"])
        self.assertAlmostEqual(full["plan"]["robust_margin"], 1002.4)
        self.assertTrue(all(t["eligibility_stable"] for t in full["targets"].values()))
        self.assertEqual(full["plan"]["tiers"], self.result()["plan"]["tiers"])

    def test_resource_constraints_independently_bind(self):
        summaries = self.result()["targets"]
        variants = [
            ("power_budget",0), ("max_active_regions",0), ("credit_budget",0)]
        for field, value in variants:
            p = copy.deepcopy(self.planning)
            p[field] = value
            result = optimize(summaries,p,p["credit_budget"])
            self.assertEqual(sum(result["tiers"].values()),0,field)
        p = copy.deepcopy(self.planning)
        for r in p["regions"].values():
            r["max_blocks"] = 0
        self.assertEqual(sum(optimize(summaries,p,30)["tiers"].values()),0)

    def test_counterfactual_authority_and_uncertainty(self):
        cases = list(probes(self.readings,self.manifest,self.operations,self.planning))
        self.assertEqual(len(cases),20)
        self.assertEqual(expected(*cases[1])["inventory"]["rejected"], ["C2.r2"])
        self.assertEqual(expected(*cases[2])["inventory"]["rejected"], ["audit-C2.r1"])
        self.assertFalse(expected(*cases[16])["plan"]["robust"])
        self.assertFalse(expected(*cases[10])["targets"]["AI"]["latency_eligible"])
        self.assertEqual(expected(*cases[10])["targets"]["AI"]["p95_bin"], "<=100")

    def test_extraction_and_missing(self):
        checks, missing = extraction(self.readings,self.truth,self.manifest,self.operations)
        self.assertEqual(len(checks),228)
        self.assertTrue(all(checks) and missing)
        bad = copy.deepcopy(self.readings)
        for row in bad["counters"]:
            if row["target"] == "DS" and row["boundary"] == "B2":
                row["requests"] = [0,0,0]
        checks, missing = extraction(bad,self.truth,self.manifest,self.operations)
        self.assertFalse(missing)
        self.assertFalse(all(checks))
        bad["units"] = "thousands"
        with self.assertRaises(AssertionError):
            reading_index(bad,self.manifest,self.operations)

    def test_score_missing_gates(self):
        checks = {k:[True] for k in COMPONENTS}
        checks["gates"] = dict.fromkeys(GATES,True)
        self.assertEqual(score(checks)["overall"],1)
        for key in GATES:
            bad = copy.deepcopy(checks)
            bad["gates"][key] = False
            self.assertEqual(score(bad)["overall"],0)
            del bad["gates"][key]
            self.assertEqual(score(bad)["overall"],0)
        checks["extraction"] = [True]*227+[False]
        self.assertAlmostEqual(score(checks)["overall"],.999123)


if __name__ == "__main__":
    unittest.main()
