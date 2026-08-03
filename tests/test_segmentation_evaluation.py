'''BraTS 3D 分割评测服务的轻量回归测试'''

from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
import unittest

import nibabel as nib
import numpy as np

from services.segmentation_evaluation import (
    dice_score,
    discover_brats_subjects,
    evaluate_brats_segmentation,
)


class SegmentationEvaluationTests(unittest.TestCase):
    def test_dice_uses_brats_composite_regions_and_excludes_double_empty(self) -> None:
        target = np.asarray([0, 1, 2, 4], dtype=np.uint8)
        prediction = np.asarray([0, 1, 0, 4], dtype=np.uint8)

        self.assertEqual(
            dice_score(prediction, target, frozenset({1, 2, 4})),
            0.8,
        )
        self.assertEqual(
            dice_score(prediction, target, frozenset({1, 4})),
            1.0,
        )
        self.assertIsNone(
            dice_score(
                np.zeros(4, dtype=np.uint8),
                np.zeros(4, dtype=np.uint8),
                frozenset({4}),
            )
        )

    def test_evaluation_discovers_subject_and_summarizes_fake_prediction(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            subject_dir = root / "BraTS-test-001"
            subject_dir.mkdir()
            affine = np.eye(4)
            target = np.zeros((2, 2, 2), dtype=np.uint8)
            target[0, 0, 0] = 1
            target[0, 0, 1] = 2
            target[0, 1, 0] = 4
            for modality in ("flair", "t1ce", "t1", "t2"):
                nib.save(
                    nib.Nifti1Image(
                        np.ones(target.shape, dtype=np.float32),
                        affine,
                    ),
                    subject_dir / f"BraTS-test-001_{modality}.nii.gz",
                )
            nib.save(
                nib.Nifti1Image(target, affine),
                subject_dir / "BraTS-test-001_seg.nii.gz",
            )

            subjects = discover_brats_subjects(root)
            self.assertEqual(len(subjects), 1)
            self.assertEqual(set(subjects[0].modalities), {"flair", "t1ce", "t1", "t2"})

            def fake_segmenter(
                modalities: dict[str, Path],
                output_dir: Path,
            ) -> dict[str, object]:
                self.assertEqual(set(modalities), {"flair", "t1ce", "t1", "t2"})
                output_dir.mkdir(parents=True, exist_ok=True)
                prediction_path = output_dir / "prediction.nii.gz"
                nib.save(nib.Nifti1Image(target, affine), prediction_path)
                return {
                    "model": "fake/segmenter",
                    "device": "cpu",
                    "mask_path": str(prediction_path),
                }

            def fake_classifier(modalities: dict[str, Path]) -> dict[str, object]:
                self.assertEqual(set(modalities), {"flair", "t1ce", "t1", "t2"})
                return {
                    "model": "fake/classifier",
                    "classification": {
                        "class": "yes",
                        "probabilities": {"yes": 0.9, "no": 0.1},
                        "threshold": 0.5,
                    },
                }

            report = evaluate_brats_segmentation(
                root,
                segmenter=fake_segmenter,
                classifier=fake_classifier,
            )

            self.assertEqual(report["successful_subjects"], 1)
            self.assertEqual(report["failed_subjects"], 0)
            self.assertEqual(report["summary"]["dice"]["WT"]["mean"], 1.0)
            self.assertEqual(report["summary"]["dice"]["TC"]["mean"], 1.0)
            self.assertEqual(report["summary"]["dice"]["ET"]["mean"], 1.0)
            classification = report["summary"]["classification"]
            self.assertEqual(classification["ground_truth_positive_cases"], 1)
            self.assertEqual(classification["ground_truth_negative_cases"], 0)
            self.assertEqual(classification["metrics"]["accuracy"], 1.0)
            self.assertEqual(classification["metrics"]["sensitivity"], 1.0)
            self.assertEqual(classification["metrics"]["brier_score"], 0.01)
            self.assertEqual(classification["calibration_bins"][-1]["count"], 1)
            self.assertNotIn("prediction_file", report["subjects"][0])


if __name__ == "__main__":
    unittest.main()
