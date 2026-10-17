'''加速后端安装命令的依赖约束测试'''

from __future__ import annotations

import unittest
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from accelerator.install import (
    PROJECT_BINARY_DEPENDENCIES,
    PYTORCH_PACKAGES,
    build_install_command,
    detect_backend,
)


class AcceleratorInstallerTests(unittest.TestCase):

    def test_auto_uses_cuda128_for_blackwell_and_preserves_older_gpus(self) -> None:
        for capabilities, expected in [("12.0\n", "cuda128"), ("10.0\n", "cuda128"), ("8.6\n12.0\n", "cuda128"), ("8.6\n", "cuda")]:
            with self.subTest(capabilities=capabilities), patch("accelerator.install.shutil.which", return_value="nvidia-smi"), patch(
                "accelerator.install.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=capabilities),
            ):
                self.assertEqual(detect_backend(), expected)

    def test_unavailable_or_unrecognized_capability_query_keeps_legacy_backend(self) -> None:
        for result in [SimpleNamespace(returncode=1, stdout=""), SimpleNamespace(returncode=0, stdout="[N/A]\n")]:
            with self.subTest(result=result), patch("accelerator.install.shutil.which", return_value="nvidia-smi"), patch(
                "accelerator.install.subprocess.run", return_value=result,
            ):
                self.assertEqual(detect_backend(), "cuda")
        with patch("accelerator.install.shutil.which", return_value="nvidia-smi"), patch(
            "accelerator.install.subprocess.run", side_effect=subprocess.TimeoutExpired("nvidia-smi", 5),
        ):
            self.assertEqual(detect_backend(), "cuda")

    def test_cuda128_command_uses_blackwell_supported_wheel(self) -> None:
        command = build_install_command("cuda128")
        self.assertIn("torch==2.7.1+cu128", command)
        self.assertIn("https://download.pytorch.org/whl/cu128", command)

    def test_default_requirements_use_the_supported_cuda_backend(self) -> None:
        requirements = (
            Path(__file__).resolve().parents[1] / "requirements.txt"
        ).read_text(encoding="utf-8")

        self.assertIn(PYTORCH_PACKAGES["cuda"][0], requirements)
        self.assertIn("https://download.pytorch.org/whl/cu121", requirements)
        self.assertNotIn(PYTORCH_PACKAGES["cpu"][0], requirements)

    def test_every_backend_keeps_project_binary_dependencies_pinned(self) -> None:
        for backend, torch_packages in PYTORCH_PACKAGES.items():
            with self.subTest(backend=backend):
                command = build_install_command(backend)
                for package in (*torch_packages, *PROJECT_BINARY_DEPENDENCIES):
                    self.assertIn(package, command)


if __name__ == "__main__":
    unittest.main()
