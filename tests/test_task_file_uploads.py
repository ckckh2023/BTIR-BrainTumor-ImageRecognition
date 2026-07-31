'''上传图片安全边界的回归测试'''

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import nibabel as nib
import numpy as np
from PIL import Image

from core.settings import SETTINGS
from core.task_definitions import AnalysisMode, InputStorageMode, ModelName
from services.task_files import (
    initialize_task,
    initialize_uploaded_task,
    initialize_uploaded_volume_task,
)


class TaskFileUploadTests(unittest.TestCase):
    '''验证上传大小、像素上限和失败后的临时文件清理'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temporary_directory.name) / "task-upload-001"
        self.task_dir.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_oversized_upload_is_rejected_before_image_validation(self) -> None:
        settings = replace(SETTINGS, max_upload_bytes=4)
        repository = Mock()

        with (
            patch("services.task_files.SETTINGS", settings),
            patch("services.task_files.task_repository", repository),
            self.assertRaisesRegex(ValueError, "超过大小限制"),
        ):
            initialize_uploaded_task(
                self.task_dir,
                BytesIO(b"12345"),
                "large.png",
            )

        self.assertFalse((self.task_dir / "input" / "image.png").exists())
        repository.save.assert_not_called()

    def test_image_with_too_many_pixels_is_rejected(self) -> None:
        upload = BytesIO()
        Image.new("RGB", (3, 2)).save(upload, format="PNG")
        upload.seek(0)
        settings = replace(SETTINGS, max_image_pixels=4)
        repository = Mock()

        with (
            patch("services.task_files.SETTINGS", settings),
            patch("services.task_files.task_repository", repository),
            self.assertRaisesRegex(ValueError, "像素超过限制"),
        ):
            initialize_uploaded_task(self.task_dir, upload, "large.png")

        self.assertFalse((self.task_dir / "input" / "image.png").exists())
        repository.save.assert_not_called()

    def test_valid_upload_is_saved_and_recorded(self) -> None:
        upload = BytesIO()
        Image.new("RGB", (2, 2)).save(upload, format="PNG")
        upload.seek(0)
        repository = Mock()

        with patch("services.task_files.task_repository", repository):
            image_path = initialize_uploaded_task(
                self.task_dir,
                upload,
                "scan.png",
                name="上传测试",
            )

        self.assertTrue(image_path.is_file())
        repository.save.assert_called_once()

    def test_local_copy_is_self_contained_and_uses_original_filename(self) -> None:
        source_image = Path(self.temporary_directory.name) / "local-scan.png"
        source_image.write_bytes(b"local-image")
        repository = Mock()

        with patch("services.task_files.task_repository", repository):
            image_path = initialize_task(
                self.task_dir,
                source_image,
                InputStorageMode.COPY,
            )

        self.assertEqual(image_path.parent, (self.task_dir / "input").resolve())
        saved_record = repository.save.call_args.args[1]
        self.assertEqual(saved_record.input.original_filename, "local-scan.png")
        self.assertNotIn("source_file", saved_record.input.model_dump())

    def test_multimodal_volume_upload_is_saved_as_a_3d_task(self) -> None:
        repository = Mock()
        uploads = {
            modality: BytesIO(f"{modality}-nifti".encode())
            for modality in ("flair", "t1ce", "t1", "t2")
        }
        filenames = {
            modality: f"patient_{modality}.nii.gz"
            for modality in uploads
        }

        with (
            patch("services.task_files.task_repository", repository),
            patch("services.task_files._validate_volume_headers"),
        ):
            stored = initialize_uploaded_volume_task(
                self.task_dir,
                uploads,
                filenames,
                name="3D test",
            )

        self.assertEqual(set(stored), {"flair", "t1ce", "t1", "t2"})
        self.assertTrue(all(path.is_file() for path in stored.values()))
        saved_record = repository.save.call_args.args[1]
        self.assertEqual(saved_record.analysis_mode, AnalysisMode.THREE_D)
        self.assertEqual(
            saved_record.expected_models,
            [ModelName.CLASSIFICATION, ModelName.SEGMENTATION],
        )
        self.assertEqual(
            set(saved_record.input.modalities or {}),
            {"flair", "t1ce", "t1", "t2"},
        )
        self.assertEqual(saved_record.input.storage_mode, "uploaded_multimodal")

    def test_multimodal_volume_upload_enforces_total_size_limit(self) -> None:
        settings = replace(SETTINGS, max_3d_upload_bytes=10)
        repository = Mock()
        uploads = {
            modality: BytesIO(b"123")
            for modality in ("flair", "t1ce", "t1", "t2")
        }
        filenames = {
            modality: f"{modality}.nii"
            for modality in uploads
        }

        with (
            patch("services.task_files.SETTINGS", settings),
            patch("services.task_files.task_repository", repository),
            self.assertRaisesRegex(ValueError, "总大小超过限制"),
        ):
            initialize_uploaded_volume_task(
                self.task_dir,
                uploads,
                filenames,
            )

        repository.save.assert_not_called()
        self.assertFalse(any((self.task_dir / "input").iterdir()))

    def test_multimodal_volume_upload_enforces_decompressed_voxel_limit(self) -> None:
        volume_bytes = nib.Nifti1Image(
            np.zeros((2, 2, 2), dtype=np.float32),
            np.eye(4),
        ).to_bytes()
        uploads = {
            modality: BytesIO(volume_bytes)
            for modality in ("flair", "t1ce", "t1", "t2")
        }
        filenames = {
            modality: f"{modality}.nii"
            for modality in uploads
        }
        settings = replace(SETTINGS, max_3d_voxels=4)
        repository = Mock()

        with (
            patch("services.task_files.SETTINGS", settings),
            patch("services.task_files.task_repository", repository),
            self.assertRaisesRegex(ValueError, "体素数超过限制"),
        ):
            initialize_uploaded_volume_task(
                self.task_dir,
                uploads,
                filenames,
            )

        repository.save.assert_not_called()
        self.assertFalse(any((self.task_dir / "input").iterdir()))


if __name__ == "__main__":
    unittest.main()
