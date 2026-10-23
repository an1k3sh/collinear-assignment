import unittest

from tlp.compiler import equivalent
from tlp.runner import run_case


class GroupHavingExamples(unittest.TestCase):
    def case(self):
        return {
            "version": 1,
            "tables": {"t": [[1, 1, 6, "a"], [2, 1, -2, "a"],
                             [3, 2, 4, "b"], [4, 3, None, "c"]], "u": []},
            "source": "single", "where": None, "value": None,
            "mode": "group", "group_by": [["col", "t", "k"]],
            "select": [["col", "t", "k"]],
            "predicate": ["gt", ["col", "t", "v"], ["lit", 0]],
        }

    def test_shared_group_is_unioned(self):
        result = run_case(self.case())
        self.assertTrue(result["ok"])
        self.assertTrue(equivalent(result["actual"], [[1], [2], [3]]))

    def test_having_preserves_duplicate_projections(self):
        case = self.case()
        total = ["agg", "sum", ["col", "t", "v"]]
        case.update(mode="having", select=[total],
                    predicate=["gt", total, ["lit", 0]])
        result = run_case(case)
        self.assertTrue(result["ok"])
        self.assertTrue(equivalent(result["actual"], [[4], [4], [None]]))


if __name__ == "__main__":
    unittest.main()
