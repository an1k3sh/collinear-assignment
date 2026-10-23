import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.codec import SyncError
from server.store import Store


class Regression(unittest.TestCase):
    def test_retry_and_key_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.sqlite"
            request = {"tenant": "a", "device": "d", "mutation": "m", "id": "x",
                       "kind": "create", "base": "0",
                       "data": {"title": "Test", "assignee": None, "visits": 0, "done": False}}
            response = Store(path).mutate(request)
            self.assertEqual(Store(path).mutate(request), response)
            with self.assertRaises(SyncError) as error:
                Store(path).mutate({**request, "data": {**request["data"], "title": "Different"}})
            self.assertEqual(error.exception.code, "idempotency_reuse")


if __name__ == "__main__":
    unittest.main()
