import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class Smoke(unittest.TestCase):
    def test_transactional_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "input.json").write_text(
                '{"warehouses":{"east":{"gear":10},"west":{}}}')
            (root / "program.stock").write_text('''
proc main() {
    let attempted: int = 0;
    transaction {
        set attempted = 9;
        reserve("aborted", "east", "gear", 3);
        emit "not_committed" {};
        assert false;
    } recover (err) {
        emit "reverted" { attempted: attempted; reason: code(err); };
    }
    reserve("live", "east", "gear", 4);
    ship("live", 2);
    emit "free" { units: available("east", "gear"); };
}
''')
            process = subprocess.run(
                [sys.executable, "-m", "stockroom", str(root / "program.stock"),
                 "--inventory", str(root / "input.json"),
                 "--out", str(root / "out.json")], capture_output=True, text=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            result = json.loads((root / "out.json").read_text())
            self.assertEqual(result["warehouses"]["east"]["gear"], 8)
            self.assertEqual(set(result["holds"]), {"live"})
            self.assertEqual(result["holds"]["live"]["remaining"], 2)
            self.assertEqual(result["events"], [
                {"id": 1, "name": "reverted", "data": {"attempted": 0, "reason": "ASSERT"}},
                {"id": 2, "name": "free", "data": {"units": 6}}])
            self.assertEqual(result["stats"], {"steps": 10, "committed": 0, "rolled_back": 1})


if __name__ == "__main__":
    unittest.main()
