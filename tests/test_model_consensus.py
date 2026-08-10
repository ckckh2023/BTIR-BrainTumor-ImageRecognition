"""双模型综合结论回归测试"""

from __future__ import annotations

import unittest

from services.model_consensus import build_model_consensus


def _segmentation(voxels: int = 0, volume_mm3: float = 0.0) -> dict:
    return {
        "regions": {
            "1": {
                "voxels": voxels,
                "volume_mm3": volume_mm3,
            }
        }
    }


class ModelConsensusTests(unittest.TestCase):
    def test_models_agree_on_segmented_abnormality(self) -> None:
        result = build_model_consensus(
            {"class": "yes", "probabilities": {"yes": 0.68}},
            _segmentation(20, 25.5),
        )

        self.assertEqual(result["consistency"], "consistent")
        self.assertEqual(result["level"], "high_probability_present")
        self.assertEqual(result["label"], "高概率存在肿瘤相关区域")
        self.assertFalse(result["requires_review"])
        self.assertTrue(result["segmentation_detected"])
        self.assertEqual(result["segmentation_volume_mm3"], 25.5)

    def test_models_agree_on_no_detected_region(self) -> None:
        result = build_model_consensus({"class": "no"}, _segmentation())

        self.assertEqual(result["consistency"], "consistent")
        self.assertFalse(result["requires_review"])
        self.assertEqual(result["level"], "likely_absent")
        self.assertIn("均未提示", result["summary"])

    def test_high_confidence_negative_with_no_segmented_region(self) -> None:
        result = build_model_consensus(
            {"class": "no", "probabilities": {"yes": 0.08}},
            _segmentation(),
        )

        self.assertEqual(result["level"], "high_probability_absent")
        self.assertEqual(result["label"], "高概率不存在肿瘤相关区域")

    def test_segmented_region_is_kept_when_classifier_is_negative(self) -> None:
        result = build_model_consensus({"class": "no"}, _segmentation(20, 25.5))

        self.assertEqual(result["consistency"], "conflicting")
        self.assertEqual(result["level"], "possible_present")
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["primary_evidence"], "segmentation")
        self.assertIn("分割模型检出区域", result["summary"])

    def test_positive_classifier_without_segmented_region_requires_review(self) -> None:
        result = build_model_consensus({"class": "yes"}, _segmentation())

        self.assertEqual(result["consistency"], "conflicting")
        self.assertEqual(result["level"], "possible_present")
        self.assertTrue(result["requires_review"])
        self.assertIn("未检出区域", result["summary"])


if __name__ == "__main__":
    unittest.main()
