import unittest
from pathlib import Path

from judge import accepted,validate,WEIGHTS


class JudgeContractTests(unittest.TestCase):
    def response(self):
        return {
            "scores":{k:4 for k in WEIGHTS},
            "evidence":{k:["Observable document evidence"] for k in WEIGHTS},
            "material_defects":[],
            "inspected_images":["original-01.png"],
        }

    def test_perfect_passes(self):
        self.assertTrue(accepted({k:4 for k in WEIGHTS}))

    def test_weighted_threshold(self):
        self.assertFalse(accepted({k:3 for k in WEIGHTS}))

    def test_critical_dimension_cannot_be_averaged_away(self):
        scores={k:4 for k in WEIGHTS};scores["navigation_furniture"]=2
        self.assertFalse(accepted(scores))

    def test_valid_response(self):
        validate(self.response(),[Path("original-01.png")])

    def test_missing_image_is_infrastructure_error(self):
        response=self.response();response["inspected_images"]=[]
        with self.assertRaises(ValueError):validate(response,[Path("original-01.png")])

    def test_boolean_is_not_a_score(self):
        response=self.response();response["scores"]["content_fidelity"]=True
        with self.assertRaises(ValueError):validate(response,[Path("original-01.png")])

    def test_missing_evidence_is_infrastructure_error(self):
        response=self.response();response["evidence"]["content_fidelity"]=[]
        with self.assertRaises(ValueError):validate(response,[Path("original-01.png")])

    def test_malformed_defect_is_infrastructure_error(self):
        response=self.response();response["material_defects"]=[{"claim":"bad"}]
        with self.assertRaises(ValueError):validate(response,[Path("original-01.png")])


if __name__=="__main__":
    unittest.main()
