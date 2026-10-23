"""Author-side grading arithmetic tests; not candidate correctness tests."""
import unittest

from grade import score


class ScoringTests(unittest.TestCase):
    def outcomes(self):
        names = [
            "test_validity_reference", "test_completeness_having",
            "test_diversity_partition_occupancy", "test_diversity_shapes",
            "test_artifact_save_replay", "test_artifact_cli_mismatch_and_error",
            "test_artifact_cli",
        ]
        return {"Suite." + name: True for name in names}

    def test_full_and_empty(self):
        self.assertEqual(score(self.outcomes())["overall"], 1.0)
        self.assertEqual(score({})["overall"], 0.0)
        self.assertEqual(score(self.outcomes())["oracle_correctness"],
                         score(self.outcomes())["validity"])

    def test_each_gate(self):
        for name in ("test_validity_reference", "test_completeness_having",
                     "test_diversity_partition_occupancy", "test_artifact_save_replay",
                     "test_artifact_cli_mismatch_and_error"):
            with self.subTest(name=name):
                outcomes = self.outcomes()
                outcomes["Suite." + name] = False
                self.assertEqual(score(outcomes)["overall"], 0.0)
                del outcomes["Suite." + name]
                self.assertEqual(score(outcomes)["overall"], 0.0)

    def test_partial_weighting(self):
        outcomes = self.outcomes()
        outcomes["Suite.test_diversity_shapes"] = False
        outcomes["Suite.test_artifact_cli"] = False
        result = score(outcomes)
        self.assertEqual(result["diversity"], 0.5)
        self.assertEqual(result["artifact_quality"], 2 / 3)
        self.assertEqual(result["overall"], round(0.45 + 0.35 / 2 + 0.2 * 2 / 3, 6))


if __name__ == "__main__":
    unittest.main()
