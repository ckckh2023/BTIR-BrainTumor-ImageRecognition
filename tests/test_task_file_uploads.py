'''四模态体数据上传安全边界的回归测试'''

from __future__ import annotations

from dataclasses import replace
import gzip
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import nibabel as nib
import numpy as np

from core.settings import SETTINGS
from services.task_files import (
    initialize_uploaded_volume_task,
    select_volume_archive_entries,
    VolumeArchiveSelectionRequired,
    volume_modality_from_filename,
)


class TaskFileUploadTests(unittest.TestCase):
    '''验证上传大小、体素上限和失败后的临时文件清理'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.task_dir = Path(self.temporary_directory.name) / "task-upload-001"
        self.task_dir.mkdir()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

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
            patch(
                "services.task_files.sha256",
                side_effect=AssertionError("上传保存后不应重新读取文件计算哈希"),
            ),
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
        self.assertEqual(saved_record.analysis_mode, "3d")
        self.assertEqual(
            set(saved_record.input.modalities or {}),
            {"flair", "t1ce", "t1", "t2"},
        )
        self.assertEqual(
            saved_record.input.modalities["flair"].sha256,
            hashlib.sha256(b"flair-nifti").hexdigest(),
        )

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

    def test_uncompressed_nii_upload_is_gzip_stored(self) -> None:
        repository = Mock()
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

        with (
            patch("services.task_files.task_repository", repository),
            patch("services.task_files._validate_volume_headers"),
        ):
            stored = initialize_uploaded_volume_task(
                self.task_dir,
                uploads,
                filenames,
                name="gzip storage test",
            )

        expected_hash = None
        for modality in ("flair", "t1ce", "t1", "t2"):
            stored_path = stored[modality]
            self.assertEqual(stored_path.name, f"{modality}.nii.gz")
            self.assertTrue(stored_path.is_file())
            stored_bytes = stored_path.read_bytes()
            self.assertEqual(gzip.decompress(stored_bytes), volume_bytes)
            expected_hash = hashlib.sha256(stored_bytes).hexdigest()

        saved_record = repository.save.call_args.args[1]
        for modality in ("flair", "t1ce", "t1", "t2"):
            record = saved_record.input.modalities[modality]
            self.assertEqual(record.path, f"input/{modality}.nii.gz")
            stored_path = stored[modality]
            self.assertEqual(record.size_bytes, stored_path.stat().st_size)
            self.assertEqual(record.sha256, expected_hash)
        self.assertEqual(
            saved_record.input.size_bytes,
            sum(stored[modality].stat().st_size for modality in stored),
        )
        stored_names = {
            path.name for path in (self.task_dir / "input").iterdir()
        }
        self.assertEqual(
            stored_names,
            {f"{modality}.nii.gz" for modality in ("flair", "t1ce", "t1", "t2")},
        )

    def test_archive_selection_finds_modalities_and_ignores_ground_truth_mask(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for modality in ("flair", "t1ce", "t1", "t2"):
                archive.writestr(f"BraTS19_case/BraTS19_case_{modality}.nii", b"nifti")
            archive.writestr("BraTS19_case/BraTS19_case_seg.nii", b"ground-truth")

        archive_bytes.seek(0)
        with zipfile.ZipFile(archive_bytes) as archive:
            selected = select_volume_archive_entries(archive)

        self.assertEqual(set(selected), {"flair", "t1ce", "t1", "t2"})
        self.assertEqual(selected["t1ce"].filename, "BraTS19_case/BraTS19_case_t1ce.nii")

    def test_archive_selection_rejects_duplicate_modality(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            for modality in ("flair", "t1ce", "t1", "t2"):
                archive.writestr(f"case_{modality}.nii", b"nifti")
            archive.writestr("case_repeat_flair.nii", b"nifti")

        archive_bytes.seek(0)
        with zipfile.ZipFile(archive_bytes) as archive:
            with self.assertRaises(VolumeArchiveSelectionRequired) as captured:
                select_volume_archive_entries(archive)

        self.assertEqual(captured.exception.modalities["flair"]["reason"], "duplicate")
        self.assertEqual(len(captured.exception.modalities["flair"]["candidates"]), 2)

    def test_filename_recognition_requires_a_complete_modality_token(self) -> None:
        self.assertEqual(volume_modality_from_filename("case_t1ce.nii.gz"), "t1ce")
        self.assertEqual(volume_modality_from_filename("case_t1.nii"), "t1")
        self.assertIsNone(volume_modality_from_filename("case_seg.nii"))
        self.assertIsNone(volume_modality_from_filename("case_t1cex.nii"))

    def test_archive_selection_allows_every_modality_to_be_manually_replaced(self) -> None:
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("case_notes.txt", b"notes")

        archive_bytes.seek(0)
        with zipfile.ZipFile(archive_bytes) as archive:
            selected = select_volume_archive_entries(
                archive,
                required_modalities=set(),
            )

        self.assertEqual(selected, {})


if __name__ == "__main__":
    unittest.main()
