import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from server.store import Store
from test_server_regressions import *  # noqa: E402,F401,F403  (regression suite)


class Smoke(unittest.TestCase):
    def test_create_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "work.sqlite")
            response = store.mutate({
                "tenant": "north", "device": "van-7", "mutation": "first",
                "id": "order", "base": "0", "kind": "create",
                "data": {"title": "Inspection", "assignee": None, "visits": 0, "done": False}})
            self.assertTrue(response["ok"])
            self.assertEqual(store.snapshot("north", 10)["rows"][0]["body"]["title"], "Inspection")


if __name__ == "__main__":
    unittest.main()
