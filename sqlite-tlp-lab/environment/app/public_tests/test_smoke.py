import json
from pathlib import Path
import unittest

from tlp.compiler import equivalent
from tlp.generator import generate
from tlp.runner import run_case


class SmokeTests(unittest.TestCase):
    def test_example(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "nullable.json"
        result = run_case(json.loads(path.read_text()))
        self.assertTrue(result["ok"])
        self.assertTrue(equivalent(result["expected"], [[7], [7], [-2], [None]]))

    def test_multisets(self):
        self.assertTrue(equivalent([[None], [1]], [[1], [None]]))
        self.assertFalse(equivalent([[1], [1]], [[1]]))
        self.assertFalse(equivalent([[1]], [["1"]]))
        self.assertFalse(equivalent([[1]], [[1.0]]))

    def test_generation(self):
        self.assertEqual(generate(5, 4), generate(5, 4))
        self.assertEqual(len(generate(5, 4)), 4)
        self.assertEqual(generate(5, 0), [])


if __name__ == "__main__":
    unittest.main()
