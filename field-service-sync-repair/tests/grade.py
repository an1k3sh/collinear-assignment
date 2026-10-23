import io
import json
import os
import unittest
from pathlib import Path

from test_service import ServiceTests


class Results(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.outcomes = {}

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[test._testMethodName] = {"passed": True}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[test._testMethodName] = {
            "passed": False, "detail": self._exc_info_to_string(err, test)}

    addError = addFailure


stream = io.StringIO()
suite = unittest.defaultTestLoader.loadTestsFromTestCase(ServiceTests)
result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Results).run(suite)
groups = {}
for name, outcome in result.outcomes.items():
    groups.setdefault(name.split("_")[1], []).append(int(outcome["passed"]))
reward = {name: sum(values) / len(values) for name, values in sorted(groups.items())}
reward["overall"] = float(result.wasSuccessful() and bool(result.testsRun))
destination = Path(os.environ.get("VERIFIER_LOG", "/logs/verifier"))
destination.mkdir(parents=True, exist_ok=True)
(destination / "reward.json").write_text(json.dumps(reward, indent=2))
(destination / "details.json").write_text(json.dumps(result.outcomes, indent=2))
(destination / "tests.log").write_text(stream.getvalue())
print(stream.getvalue())
print(json.dumps(reward, sort_keys=True))
raise SystemExit(0 if result.wasSuccessful() else 1)
