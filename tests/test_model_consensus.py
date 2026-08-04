"""Regression coverage for the deterministic segmentation-first conclusion."""

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
        result = build_model_consensus({"class": "yes"}, _segmentation(20, 25.5))

        self.assertEqual(result["consistency"], "consistent")
        self.assertFalse(result["requires_review"])
        self.assertTrue(result["segmentation_detected"])
        self.assertEqual(result["segmentation_volume_mm3"], 25.5)

    def test_models_agree_on_no_detected_region(self) -> None:
        result = build_model_consensus({"class": "no"}, _segmentation())

        self.assertEqual(result["consistency"], "consistent")
        self.assertFalse(result["requires_review"])
        self.assertIn("未提示明显", result["summary"])

    def test_segmented_region_is_kept_when_classifier_is_negative(self) -> None:
        result = build_model_consensus({"class": "no"}, _segmentation(20, 25.5))

        self.assertEqual(result["consistency"], "conflicting")
        self.assertTrue(result["requires_review"])
        self.assertEqual(result["primary_evidence"], "segmentation")
        self.assertIn("检出异常区域", result["summary"])

    def test_positive_classifier_without_segmented_region_requires_review(self) -> None:
        result = build_model_consensus({"class": "yes"}, _segmentation())

        self.assertEqual(result["consistency"], "conflicting")
        self.assertTrue(result["requires_review"])
        self.assertIn("未检出明确异常区域", result["summary"])


if __name__ == "__main__":
    unittest.main()
