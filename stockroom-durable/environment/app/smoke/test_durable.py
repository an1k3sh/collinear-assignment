import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DurableSmoke(unittest.TestCase):
    def test_pause_inside_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "program.stock"
            incoming = root / "inventory.json"
            output = root / "out.json"
            checkpoint = root / "checkpoint.json"
            source.write_text('''
proc main() {
 let x:int=1;
 transaction {
   set x=2; reserve("h","east","gear",3);
   emit "discarded" {}; pause "approval"; assert false;
 } recover(e) { emit code(e) {x:x;}; }
}
''')
            incoming.write_text('{"warehouses":{"east":{"gear":10}}}')
            command = [sys.executable, "-m", "stockroom", str(source),
                       "--inventory", str(incoming), "--out", str(output),
                       "--checkpoint", str(checkpoint)]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 10, first.stderr)
            self.assertFalse(output.exists())
            saved = json.loads(checkpoint.read_text())
            self.assertEqual(saved["label"], "approval")
            self.assertEqual(saved["pause_count"], 1)
            checksum = saved.pop("checksum")
            canonical = json.dumps(saved, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=True, allow_nan=False).encode("utf-8")
            self.assertEqual(checksum, hashlib.sha256(canonical).hexdigest())
            before = checkpoint.read_bytes()
            second = subprocess.run(command + ["--resume", str(checkpoint)],
                                    capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(checkpoint.read_bytes(), before)
            result = json.loads(output.read_text())
            self.assertEqual(result["holds"], {})
            self.assertEqual(result["warehouses"]["east"]["gear"], 10)
            self.assertEqual(result["events"],
                             [{"id": 1, "name": "ASSERT", "data": {"x": 1}}])
            self.assertEqual(result["stats"],
                             {"steps": 8, "committed": 0, "rolled_back": 1})


if __name__ == "__main__":
    unittest.main()
