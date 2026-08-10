'''SuperLightNet 三维推理边界的轻量回归测试'''

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import nibabel as nib
import numpy as np
import torch

from models.segmentation3d import inference
from superlightnet import THPAEncFR3


class Segmentation3DTests(unittest.TestCase):
    def test_runtime_mode_switches_between_deterministic_and_fast(self) -> None:
        original_deterministic = torch.are_deterministic_algorithms_enabled()
        original_benchmark = torch.backends.cudnn.benchmark
        original_cudnn_deterministic = torch.backends.cudnn.deterministic
        original_matmul_tf32 = getattr(torch.backends.cuda.matmul, "allow_tf32", None)
        original_cudnn_tf32 = getattr(torch.backends.cudnn, "allow_tf32", None)
        try:
            inference._configure_inference_runtime(0, fast_inference=False)
            self.assertTrue(torch.are_deterministic_algorithms_enabled())
            self.assertFalse(torch.backends.cudnn.benchmark)
            self.assertTrue(torch.backends.cudnn.deterministic)

            inference._configure_inference_runtime(0, fast_inference=True)
            self.assertFalse(torch.are_deterministic_algorithms_enabled())
            self.assertTrue(torch.backends.cudnn.benchmark)
            self.assertFalse(torch.backends.cudnn.deterministic)
        finally:
            torch.use_deterministic_algorithms(original_deterministic)
            torch.backends.cudnn.benchmark = original_benchmark
            torch.backends.cudnn.deterministic = original_cudnn_deterministic
            if original_matmul_tf32 is not None:
                torch.backends.cuda.matmul.allow_tf32 = original_matmul_tf32
            if original_cudnn_tf32 is not None:
                torch.backends.cudnn.allow_tf32 = original_cudnn_tf32

    def test_cuda_accumulator_requires_safe_free_memory(self) -> None:
        shape = (240, 240, 155)
        cuda = torch.device("cuda")

        with patch.object(
            inference.torch.cuda,
            "mem_get_info",
            return_value=(4 * 1024**3, 8 * 1024**3),
        ):
            selected = inference._select_accumulator_device(shape, cuda)
        self.assertEqual(selected, cuda)

        with patch.object(
            inference.torch.cuda,
            "mem_get_info",
            return_value=(2 * 1024**3, 8 * 1024**3),
        ):
            selected = inference._select_accumulator_device(shape, cuda)
        self.assertEqual(selected, torch.device("cpu"))

    def test_cuda_accumulator_oom_retries_with_cpu_accumulator(self) -> None:
        images = np.zeros((16, 16, 16, 4), dtype=np.float32)
        cpu_logits = torch.zeros((1, 4, 16, 16, 16), dtype=torch.float32)

        with (
            patch.object(
                inference,
                "_stage_input_tensor",
                return_value=(
                    inference._to_tensor(images),
                    torch.device("cuda"),
                ),
            ),
            patch.object(
                inference,
                "sliding_window_inference",
                side_effect=[torch.cuda.OutOfMemoryError(), cpu_logits],
            ) as sliding_window,
            patch.object(inference.torch.cuda, "empty_cache") as empty_cache,
        ):
            labels = inference._run_full_volume_inference(
                images,
                torch.nn.Identity(),
                torch.device("cuda"),
                roi_size=(16, 16, 16),
                overlap=0.5,
                progress=False,
            )

        self.assertEqual(labels.shape, images.shape[:3])
        self.assertEqual(sliding_window.call_count, 2)
        self.assertEqual(
            sliding_window.call_args_list[1].kwargs["device"],
            torch.device("cpu"),
        )
        empty_cache.assert_called_once_with()

    def test_full_volume_inference_reports_window_progress(self) -> None:
        images = np.zeros((16, 16, 16, 4), dtype=np.float32)
        logits = torch.zeros((1, 4, 16, 16, 16), dtype=torch.float32)
        progress_values: list[float] = []

        def fake_sliding_window(inputs, *, predictor, **kwargs):
            for _ in range(4):
                predictor(inputs)
            return logits

        with (
            patch.object(
                inference,
                "_stage_input_tensor",
                return_value=(
                    inference._to_tensor(images),
                    torch.device("cpu"),
                ),
            ),
            patch.object(
                inference,
                "sliding_window_inference",
                side_effect=fake_sliding_window,
            ),
            patch.object(
                inference,
                "_count_sliding_windows",
                return_value=4,
            ),
        ):
            labels = inference._run_full_volume_inference(
                images,
                Mock(),
                torch.device("cpu"),
                roi_size=(16, 16, 16),
                overlap=0.25,
                progress=False,
                progress_callback=progress_values.append,
            )

        self.assertEqual(labels.shape, images.shape[:3])
        self.assertEqual(progress_values, [0.25, 0.5, 0.75, 1.0])

    def test_full_volume_inference_checks_cancel_before_each_window(self) -> None:
        images = np.zeros((16, 16, 16, 4), dtype=np.float32)
        model = Mock(return_value=torch.zeros((1, 4, 16, 16, 16)))
        cancel_calls = {"count": 0}

        def cancel_callback() -> None:
            cancel_calls["count"] += 1
            if cancel_calls["count"] == 2:
                raise RuntimeError("cancel current segmentation")

        def fake_sliding_window(inputs, *, predictor, **kwargs):
            predictor(inputs)
            predictor(inputs)

        with (
            patch.object(
                inference,
                "_stage_input_tensor",
                return_value=(inference._to_tensor(images), torch.device("cpu")),
            ),
            patch.object(
                inference,
                "sliding_window_inference",
                side_effect=fake_sliding_window,
            ),
            self.assertRaisesRegex(RuntimeError, "cancel current segmentation"),
        ):
            inference._run_full_volume_inference(
                images,
                model,
                torch.device("cpu"),
                roi_size=(16, 16, 16),
                overlap=0.25,
                progress=False,
                cancel_callback=cancel_callback,
            )

        model.assert_called_once()

    def test_input_staging_oom_falls_back_to_cpu(self) -> None:
        images = np.zeros((16, 16, 16, 4), dtype=np.float32)
        tensor = Mock(spec=torch.Tensor)
        tensor.to.side_effect = torch.cuda.OutOfMemoryError()

        with (
            patch.object(inference, "_to_tensor", return_value=tensor),
            patch.object(inference.torch.cuda, "empty_cache") as empty_cache,
        ):
            staged, accumulator = inference._stage_input_tensor(
                images,
                torch.device("cuda"),
                torch.device("cuda"),
            )

        self.assertIs(staged, tensor)
        self.assertEqual(accumulator, torch.device("cpu"))
        empty_cache.assert_called_once_with()

    def test_internal_et_label_is_mapped_to_brats_label_four(self) -> None:
        internal = np.asarray([0, 1, 2, 3], dtype=np.uint8)

        mapped = inference._to_brats_labels(internal)

        np.testing.assert_array_equal(
            mapped,
            np.asarray([0, 1, 2, 4], dtype=np.uint8),
        )

    def test_morphology_statistics_summarizes_components_without_image_data(self) -> None:
        segmentation = np.zeros((8, 8, 8), dtype=np.uint8)
        segmentation[1:3, 1:3, 1:3] = 1
        segmentation[5, 5, 5] = 4

        reference = nib.Nifti1Image(
            np.zeros(segmentation.shape, dtype=np.float32),
            np.diag([1.0, 2.0, 3.0, 1.0]),
        )
        result = inference._morphology_statistics(segmentation, reference)

        self.assertEqual(result["connected_components"], 2)
        self.assertEqual(result["largest_component_voxels"], 8)
        self.assertEqual(result["largest_component_volume_mm3"], 48.0)
        self.assertEqual(result["largest_component_ratio"], 0.888889)
        self.assertEqual(result["bounding_box_size_voxels"], [2, 2, 2])
        self.assertEqual(result["bounding_box_size_mm"], [2.0, 4.0, 6.0])
        self.assertEqual(result["bounding_box_fill_ratio"], 1.0)
        self.assertEqual(result["centroid_normalized"], [0.214286, 0.214286, 0.214286])

        composites = inference._composite_region_statistics(segmentation, reference)
        self.assertEqual(composites["WT"]["voxels"], 9)
        self.assertEqual(composites["TC"]["volume_mm3"], 54.0)
        self.assertEqual(composites["ET"]["share_of_non_background"], 0.11111111)

    def test_evaluation_direction_is_independent_of_random_generator(self) -> None:
        block = THPAEncFR3(in_channels=8, expr=2)
        block.inference_direction = 2
        block.eval()
        inputs = torch.randn((1, 8, 16, 16, 16))

        torch.manual_seed(10)
        first = block(inputs)
        torch.manual_seed(999)
        second = block(inputs)

        torch.testing.assert_close(first, second, rtol=0, atol=0)

    def test_saved_segmentation_preserves_reference_space(self) -> None:
        affine = np.asarray(
            [
                [-1.0, 0.0, 0.0, 0.0],
                [0.0, -1.0, 0.0, 17.0],
                [0.0, 0.0, 1.5, -2.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        )
        reference = nib.Nifti1Image(
            np.zeros((20, 18, 17), dtype=np.float32),
            affine,
        )
        segmentation = np.full(reference.shape, 4, dtype=np.uint8)

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "prediction.nii.gz"
            inference._save_segmentation(
                segmentation,
                reference,
                output_path,
            )
            saved = nib.load(output_path)

            self.assertEqual(saved.shape, reference.shape)
            np.testing.assert_allclose(saved.affine, affine)
            self.assertEqual(
                set(np.unique(np.asarray(saved.dataobj)).tolist()),
                {4},
            )


if __name__ == "__main__":
    unittest.main()
