import tempfile
import unittest
from pathlib import Path

from runtime import Store


class Smoke(unittest.TestCase):
    def test_classification_and_day_corrections(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "board.sqlite")
            try:
                store.upgrade(("inner",))
                store.apply("seed", [
                    {"table": "orders", "id": "o1", "row": {
                        "id": "o1", "account": "A", "day": "d1", "cents": 80}},
                    {"table": "tags", "id": "t1", "row": {
                        "id": "t1", "account": "A", "segment": "retail"}},
                ])
                store.apply("reclassify", [
                    {"table": "tags", "id": "t1", "row": {
                        "id": "t1", "account": "A", "segment": "trade"}},
                ])
                self.assertEqual(store.snapshot()[0]["segment"], "trade")
                store.apply("move", [
                    {"table": "orders", "id": "o1", "row": {
                        "id": "o1", "account": "A", "day": None, "cents": 80}},
                ])
                rows = store.snapshot()
                self.assertEqual(len(rows), 1)
                self.assertIsNone(rows[0]["day"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()

