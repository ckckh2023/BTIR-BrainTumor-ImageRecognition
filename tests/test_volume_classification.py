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
            progress = []
            with_progress = prepare_volume_slices(path, max_slices=3, progress_callback=progress.append)

        self.assertEqual(progress, [0.5, 0.5 + 0.5 / 3, 0.5 + 1 / 3, 1.0])
        self.assertEqual(with_progress.indices, prepared.indices)
        for actual, expected in zip(with_progress.images, prepared.images, strict=True):
            np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected))

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

    def test_classification_reports_completed_batches_without_changing_predictions(self) -> None:
        loaded = LoadedBinarySliceClassifier(
            model=_FakeVitModel(), processor=_FakeVitProcessor(),
            no_index=0, yes_index=1, device=torch.device("cpu"),
            checkpoint_name="model.safetensors",
        )
        images = [Image.new("RGB", (20, 20)) for _ in range(5)]
        progress = []
        expected = predict_images(loaded, images, batch_size=2)
        actual = predict_images(loaded, images, batch_size=2, progress_callback=progress.append)
        self.assertEqual(actual, expected)
        self.assertEqual(progress, [0.4, 0.8, 1.0])

    def test_classification_service_reports_preparation_loading_and_inference(self) -> None:
        loaded = LoadedBinarySliceClassifier(
            model=_FakeVitModel(), processor=_FakeVitProcessor(),
            no_index=0, yes_index=1, device=torch.device("cpu"),
            checkpoint_name="model.safetensors",
        )
        prepared = SimpleNamespace(
            images=[Image.new("RGB", (20, 20)) for _ in range(3)],
            indices=(0, 1, 2), canonical_shape=(20, 20, 3),
            foreground_slice_count=3, intensity_window=(0.0, 1.0),
        )
        settings = SimpleNamespace(
            volume_classifier_modality="flair", vit_classifier_max_slices=3,
            vit_classifier_batch_size=2, vit_classifier_threshold=0.5,
            device="cpu",
        )
        events = []
        with (
            patch("services.inference_service.SETTINGS", settings),
            patch("services.inference_service.prepare_volume_slices", return_value=prepared),
            patch("services.inference_service._load_vit_classifier_namespace",
                  return_value={"torch": torch, "predict_images": predict_images}),
            patch("services.inference_service._load_vit_classifier_model", return_value=loaded),
        ):
            result = classify_volume(
                {"flair": Path("flair.nii.gz")},
                progress_callback=lambda stage, fraction: events.append((stage, fraction)),
            )
        self.assertEqual(events[0], ("正在读取分类切片", 0.0))
        self.assertIn(("正在加载分类模型", 0.125), events)
        self.assertIn(("3D 分类推理中", 0.25 + 0.625 * (2 / 3)), events)
        self.assertEqual(events[-1], ("分类结果已生成", 1.0))
        self.assertEqual([fraction for _, fraction in events], sorted(fraction for _, fraction in events))
        self.assertEqual(result["classification"]["evaluated_slices"], 3)

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
        self.assertEqual(
            result["probability_statistics"],
            {
                "mean_yes_probability": 0.5,
                "stddev_yes_probability": 0.353553,
                "min_yes_probability": 0.1,
                "max_yes_probability": 0.9,
                "median_yes_probability": 0.5,
                "positive_slice_ratio": 0.5,
            },
        )
        self.assertEqual(result["threshold_margin"], -0.05)
        self.assertEqual(
            result["positive_slice_structure"],
            {
                "positive_runs": 1,
                "longest_positive_run_samples": 2,
                "positive_span_samples": 2,
            },
        )
        self.assertEqual(
            result["probability_histogram"],
            [
                {"lower": 0.0, "upper": 0.2, "count": 1},
                {"lower": 0.2, "upper": 0.4, "count": 1},
                {"lower": 0.4, "upper": 0.6, "count": 0},
                {"lower": 0.6, "upper": 0.8, "count": 0},
                {"lower": 0.8, "upper": 1.0, "count": 2},
            ],
        )
        self.assertEqual(len(result["slice_probability_series"]), 4)
        self.assertEqual(result["slice_probability_series"][0], {"slice_index": 10, "yes_probability": 0.1})

    def test_classification_error_is_not_replaced_by_another_model(self) -> None:
        with (
            patch(
                "services.inference_service.prepare_volume_slices",
                side_effect=RuntimeError("local model unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "local model unavailable"),
        ):
            classify_volume({"flair": Path("flair.nii.gz")})

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
