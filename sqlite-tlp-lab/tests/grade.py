from __future__ import annotations

import json
import os
from pathlib import Path
import traceback
import unittest


def score(outcomes: dict[str, bool]) -> dict[str, float]:
    scores = {}
    for category in ("validity", "completeness", "diversity", "artifact"):
        values = [passed for name, passed in outcomes.items() if ".test_" + category + "_" in name]
        scores[category] = sum(values) / len(values) if values else 0.0
    required_suffixes = (
        ".test_diversity_partition_occupancy",
        ".test_artifact_save_replay",
        ".test_artifact_cli_mismatch_and_error",
    )
    required_pass = all(
        any(name.endswith(suffix) and passed for name, passed in outcomes.items())
        for suffix in required_suffixes
    )
    gate = scores["validity"] == 1.0 and scores["completeness"] == 1.0 and required_pass
    return {
        "overall": round((0.45 * scores["completeness"] + 0.35 * scores["diversity"]
                          + 0.20 * scores["artifact"]) if gate else 0.0, 6),
        "validity": scores["validity"], "oracle_correctness": scores["validity"],
        "completeness": scores["completeness"],
        "diversity": scores["diversity"], "artifact_quality": scores["artifact"],
    }


def main() -> int:
    log = Path(os.environ.get("VERIFIER_LOG", "/logs/verifier"))
    log.mkdir(parents=True, exist_ok=True)
    zero = {"overall": 0.0, "validity": 0.0, "completeness": 0.0,
            "diversity": 0.0, "artifact_quality": 0.0,
            "oracle_correctness": 0.0, "input_validity_rate": 0.0}
    (log / "reward.json").write_text(json.dumps(zero))
    outcomes = {}

    class Recorded(unittest.TextTestResult):
        def startTest(self, test):
            outcomes[test.id()] = False
            super().startTest(test)

        def addSuccess(self, test):
            outcomes[test.id()] = True
            super().addSuccess(test)

    try:
        suite = unittest.defaultTestLoader.discover(str(Path(__file__).parent), pattern="test_tlp.py")
        result = unittest.TextTestRunner(verbosity=2, resultclass=Recorded).run(suite)
        reward = score(outcomes)
        (log / "reward.json").write_text(json.dumps(reward, indent=2) + "\n")
        (log / "details.json").write_text(json.dumps(outcomes, indent=2) + "\n")
        from input_validity import measure_candidate
        diagnostics = measure_candidate()
        (log / "input-validity.json").write_text(json.dumps(diagnostics, indent=2) + "\n")
        reward["input_validity_rate"] = diagnostics["input_validity_rate"]
        (log / "reward.json").write_text(json.dumps(reward, indent=2) + "\n")
        return 0 if result.wasSuccessful() else 1
    except Exception:
        traceback.print_exc()
        # A broken measurement must not leave a success-shaped reward.
        (log / "reward.json").write_text(json.dumps(zero, indent=2) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
