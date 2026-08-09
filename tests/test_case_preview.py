import tempfile
import unittest
from pathlib import Path

import nibabel as nib
import numpy as np

from services.case_preview import render_case_preview


class CasePreviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="btir-preview-test-"))
        shape = (20, 20, 12)
        self.modalities = {}
        for key in ("flair", "t1ce", "t1", "t2"):
            data = np.random.default_rng(0).random(shape).astype(np.float32) * 500
            path = self.tmp / f"{key}.nii.gz"
            nib.save(nib.Nifti1Image(data, np.eye(4)), path)
            self.modalities[key] = path

        mask = np.zeros(shape, dtype=np.uint8)
        mask[8:13, 8:13, 5:8] = 1
        mask[10:12, 10:12, 6:7] = 2
        mask[11:12, 11:12, 6:7] = 4
        self.mask_path = self.tmp / "mask.nii.gz"
        nib.save(nib.Nifti1Image(mask, np.eye(4)), self.mask_path)

    def tearDown(self) -> None:
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_preview_png_is_rendered_for_tumor_slice(self) -> None:
        output = self.tmp / "preview.png"
        result = render_case_preview(self.modalities, self.mask_path, output)
        self.assertEqual(result, output)
        self.assertTrue(output.is_file())
        self.assertGreater(output.stat().st_size, 1000)
        self.assertTrue(output.read_bytes().startswith(b"\x89PNG"))

    def test_preview_is_rendered_when_mask_has_no_tumor(self) -> None:
        empty_mask = self.tmp / "empty_mask.nii.gz"
        nib.save(nib.Nifti1Image(np.zeros((20, 20, 12), dtype=np.uint8), np.eye(4)), empty_mask)
        output = self.tmp / "preview_empty.png"
        result = render_case_preview(self.modalities, empty_mask, output)
        self.assertEqual(result, output)
        self.assertTrue(output.is_file())

    def test_preview_skips_modalities_with_a_different_grid(self) -> None:
        mismatch = self.tmp / "t2_mismatch.nii.gz"
        nib.save(
            nib.Nifti1Image(np.zeros((20, 20, 4), dtype=np.float32), np.eye(4)),
            mismatch,
        )
        self.modalities["t2"] = mismatch
        output = self.tmp / "preview_mismatch.png"
        result = render_case_preview(self.modalities, self.mask_path, output)
        self.assertEqual(result, output)
        self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
