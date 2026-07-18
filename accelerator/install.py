'''为当前机器安装 CPU、CUDA 或 ROCm 版 PyTorch'''

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


PYTORCH_INDEXES = {
    "cpu": "https://download.pytorch.org/whl/cpu",
    "cuda": "https://download.pytorch.org/whl/cu128",
    "rocm": "https://download.pytorch.org/whl/rocm6.3",
}
PYTORCH_PACKAGES = {
    "cpu": ["torch==2.7.1+cpu", "torchvision==0.22.1+cpu"],
    "cuda": ["torch==2.7.1+cu128", "torchvision==0.22.1+cu128"],
    "rocm": ["torch==2.7.1+rocm6.3", "torchvision==0.22.1+rocm6.3"],
}


def detect_backend() -> str:
    '''根据驱动工具检测本机可使用的加速后端'''
    if shutil.which("nvidia-smi"):
        return "cuda"
    if platform.system() == "Linux" and (
        shutil.which("rocminfo") or Path("/opt/rocm").exists()
    ):
        return "rocm"
    return "cpu"


def validate_backend(backend: str) -> None:
    '''验证所选后端与操作系统是否匹配'''
    system = platform.system()
    machine = platform.machine().lower()
    if machine not in {"amd64", "x86_64"}:
        raise ValueError("当前安装器仅支持 x86_64 / AMD64 平台")
    if backend == "rocm" and system != "Linux":
        raise ValueError("ROCm 仅支持 Linux AMD GPU 服务器，Windows 请使用 CPU 或 CUDA")
    if backend == "cuda" and system not in {"Windows", "Linux"}:
        raise ValueError("CUDA 安装器仅支持 Windows 或 Linux")


def build_install_command(backend: str) -> list[str]:
    '''生成使用官方 PyTorch 源的 pip 安装命令'''
    return [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "--force-reinstall",
        "--index-url",
        PYTORCH_INDEXES[backend],
        "--extra-index-url",
        "https://pypi.org/simple",
        *PYTORCH_PACKAGES[backend],
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="安装当前项目所需的 PyTorch 加速后端"
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "cpu", "cuda", "rocm"],
        default="auto",
        help="auto 根据本机驱动检测；默认 auto",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅显示将执行的安装命令，不下载或修改环境",
    )
    args = parser.parse_args()

    backend = detect_backend() if args.backend == "auto" else args.backend
    validate_backend(backend)
    command = build_install_command(backend)
    print(f"选择的后端：{backend}")
    print("将执行：")
    print(" ".join(command))
    if args.dry_run:
        return 0

    completed = subprocess.run(command, check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
