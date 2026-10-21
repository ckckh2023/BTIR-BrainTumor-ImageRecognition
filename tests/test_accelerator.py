'''加速后端安装命令的依赖约束测试'''

from __future__ import annotations

import unittest
from pathlib import Path

from accelerator.install import (
    PROJECT_BINARY_DEPENDENCIES,
    PYTORCH_PACKAGES,
    build_install_command,
)


class AcceleratorInstallerTests(unittest.TestCase):

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
