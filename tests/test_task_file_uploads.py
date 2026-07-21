'''上传图片安全边界的回归测试'''

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from core.settings import SETTINGS
from services.task_files import initialize_uploaded_task


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


if __name__ == "__main__":
    unittest.main()
