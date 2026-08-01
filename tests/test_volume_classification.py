"""Tests for the single local ViT patient-classification route."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import nibabel as nib
import numpy as np
import torch
from PIL import Image

from models.classification.vit_binary import (
    LoadedBinarySliceClassifier,
    predict_images,
)
from processing.volume_classification import (
    aggregate_mean_slice_predictions,
    prepare_volume_slices,
)
from services.inference_service import classify_volume


class _FakeVitProcessor:
    def __call__(self, *, images, return_tensors):
        del return_tensors
        return {"pixel_values": torch.ones((len(images), 3, 8, 8))}


class _FakeVitModel(torch.nn.Module):
    def forward(self, *, pixel_values):
        logits = torch.tensor([-1.0, 1.0], device=pixel_values.device)
        return SimpleNamespace(
            logits=logits.unsqueeze(0).repeat(pixel_values.shape[0], 1)
        )


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

    def test_local_vit_returns_binary_slice_scores(self) -> None:
        loaded = LoadedBinarySliceClassifier(
            model=_FakeVitModel(),
            processor=_FakeVitProcessor(),
            no_index=0,
            yes_index=1,
            device=torch.device("cpu"),
            checkpoint_name="model.safetensors",
        )

        predictions = predict_images(
            loaded,
            [Image.new("RGB", (20, 20)), Image.new("L", (20, 20))],
            batch_size=1,
        )

        self.assertEqual(len(predictions), 2)
        self.assertTrue(all(item["class"] == "yes" for item in predictions))
        self.assertTrue(all(item["probabilities"]["yes"] > 0.8 for item in predictions))

    def test_mean_aggregation_uses_all_slices_and_configured_threshold(self) -> None:
        result = aggregate_mean_slice_predictions(
            [10, 11, 12, 13],
            [
                self._prediction(0.1),
                self._prediction(0.2),
                self._prediction(0.9),
                self._prediction(0.8),
            ],
            modality="flair",
            threshold=0.55,
        )

        self.assertEqual(result["class"], "no")
        self.assertEqual(result["probabilities"]["yes"], 0.5)
        self.assertEqual(result["evaluated_slices"], 4)
        self.assertEqual(result["aggregation"], "mean_probability")
        self.assertEqual(result["method"], "vit_binary_multislice_mean")
        self.assertEqual(result["evidence_slices"][0]["slice_index"], 12)

    def test_classification_error_is_not_replaced_by_another_model(self) -> None:
        with (
            patch(
                "services.inference_service._classify_volume_vit",
                side_effect=RuntimeError("local model unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "local model unavailable"),
        ):
            classify_volume({})

    @staticmethod
    def _prediction(yes_probability: float) -> dict[str, object]:
        return {
            "class": "yes" if yes_probability >= 0.5 else "no",
            "probabilities": {
                "no": 1.0 - yes_probability,
                "yes": yes_probability,
            },
        }


if __name__ == "__main__":
    unittest.main()
