'''3D NIfTI 切片准备、批量分类与患者级聚合测试。'''

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np
import torch
from PIL import Image

from models.classification.inference import predict_images
from processing.volume_classification import (
    aggregate_slice_predictions,
    prepare_volume_slices,
)


class _FixedYesModel(torch.nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.anchor = torch.nn.Parameter(torch.zeros(1))

    def forward(self, inputs: torch.Tensor) -> torch.Tensor:
        logits = torch.tensor([-1.0, 1.0], device=inputs.device)
        return logits.unsqueeze(0).repeat(inputs.shape[0], 1)


class VolumeClassificationTests(unittest.TestCase):
    def test_prepare_volume_slices_canonicalizes_and_limits_axial_slices(self) -> None:
        data = np.zeros((10, 12, 8), dtype=np.float32)
        for index in range(1, 7):
            data[2:8, 3:10, index] = np.arange(42, dtype=np.float32).reshape(
                6, 7
            ) + index * 10
        affine = np.asarray(
            [
                [-1.0, 0.0, 0.0, 9.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.5, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "flair.nii.gz"
            nib.save(nib.Nifti1Image(data, affine), path)
            prepared = prepare_volume_slices(path, max_slices=3)

        self.assertEqual(prepared.canonical_shape, (10, 12, 8))
        self.assertEqual(len(prepared.images), 3)
        self.assertEqual(len(prepared.indices), 3)
        self.assertEqual(tuple(sorted(prepared.indices)), prepared.indices)
        self.assertTrue(all(image.mode == "RGB" for image in prepared.images))
        self.assertGreater(prepared.intensity_window[1], prepared.intensity_window[0])

    def test_prepare_volume_slices_rejects_empty_volume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.nii.gz"
            nib.save(
                nib.Nifti1Image(
                    np.zeros((8, 8, 8), dtype=np.float32),
                    np.eye(4),
                ),
                path,
            )
            with self.assertRaisesRegex(ValueError, "空体积"):
                prepare_volume_slices(path, max_slices=4)

    def test_batch_predictor_reuses_single_image_preprocessing_contract(self) -> None:
        images = [
            Image.new("RGB", (20, 20), color=32),
            Image.new("L", (20, 20), color=128),
        ]
        config = {
            "class_names": ["no", "yes"],
            "normalization": {
                "mean": [0.485, 0.456, 0.406],
                "std": [0.229, 0.224, 0.225],
            },
        }

        predictions = predict_images(
            _FixedYesModel(),
            images,
            config,
            batch_size=1,
        )

        self.assertEqual(len(predictions), 2)
        self.assertTrue(all(item["class"] == "yes" for item in predictions))
        self.assertTrue(all(item["confidence"] > 0.5 for item in predictions))

    def test_top_fraction_aggregation_returns_patient_level_evidence(self) -> None:
        predictions = [
            self._prediction(0.1),
            self._prediction(0.2),
            self._prediction(0.9),
            self._prediction(0.8),
        ]

        result = aggregate_slice_predictions(
            [10, 11, 12, 13],
            predictions,
            modality="flair",
            top_fraction=0.5,
        )

        self.assertEqual(result["class"], "yes")
        self.assertEqual(result["probabilities"]["yes"], 0.85)
        self.assertEqual(result["top_k"], 2)
        self.assertEqual(result["evaluated_slices"], 4)
        self.assertEqual(result["positive_slices"], 2)
        self.assertEqual(
            [item["slice_index"] for item in result["evidence_slices"]],
            [12, 13],
        )
        self.assertTrue(result["experimental"])

    @staticmethod
    def _prediction(yes_probability: float) -> dict[str, object]:
        no_probability = 1.0 - yes_probability
        predicted_class = "yes" if yes_probability >= no_probability else "no"
        return {
            "class": predicted_class,
            "probabilities": {
                "no": no_probability,
                "yes": yes_probability,
            },
        }


if __name__ == "__main__":
    unittest.main()
