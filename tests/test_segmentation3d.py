'''SuperLightNet 三维推理边界的轻量回归测试'''

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np
import torch

from models.segmentation3d import inference
from Jnetworks.superlightnet import THPAEncFR3


class Segmentation3DTests(unittest.TestCase):
    def test_internal_et_label_is_mapped_to_brats_label_four(self) -> None:
        internal = np.asarray([0, 1, 2, 3], dtype=np.uint8)

        mapped = inference._to_brats_labels(internal)

        np.testing.assert_array_equal(
            mapped,
            np.asarray([0, 1, 2, 4], dtype=np.uint8),
        )

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
