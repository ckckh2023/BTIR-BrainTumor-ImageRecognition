'''推理设备选择与运行状态检测'''

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class RuntimeStatus:
    '''当前 PyTorch 实际使用的推理后端信息'''

    requested_device: str
    active_device: str
    backend: str
    accelerator_available: bool
    device_name: str | None
    device_count: int
    torch_version: str
    cuda_version: str | None
    rocm_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_device(value: str) -> str:
    '''验证并标准化设备配置 ROCm 在 PyTorch 中同样使用 cuda 设备名'''
    device = value.strip().lower()
    if device in {"cpu", "cuda", "auto"} or re.fullmatch(r"cuda:\d+", device):
        return device
    raise ValueError("BTIR_DEVICE 仅支持 cpu、cuda、cuda:序号 或 auto")


def resolve_device(torch: Any, requested_device: str) -> Any:
    '''根据配置和当前 PyTorch 后端返回实际推理设备'''
    requested_device = validate_device(requested_device)
    accelerator_available = bool(torch.cuda.is_available())

    if requested_device == "auto":
        return torch.device("cuda" if accelerator_available else "cpu")
    if requested_device.startswith("cuda") and not accelerator_available:
        raise ValueError("BTIR_DEVICE 指定了 GPU，但当前 PyTorch 未检测到 CUDA 或 ROCm 设备")
    return torch.device(requested_device)


def get_runtime_status(requested_device: str) -> RuntimeStatus:
    '''返回 CPU、NVIDIA CUDA 或 AMD ROCm 的实际运行状态'''
    import torch

    device = resolve_device(torch, requested_device)
    accelerator_available = bool(torch.cuda.is_available())
    rocm_version = getattr(torch.version, "hip", None)
    cuda_version = getattr(torch.version, "cuda", None)

    if device.type == "cpu":
        backend = "cpu"
        device_name = None
    elif rocm_version:
        backend = "rocm"
        device_name = torch.cuda.get_device_name(device)
    else:
        backend = "cuda"
        device_name = torch.cuda.get_device_name(device)

    return RuntimeStatus(
        requested_device=validate_device(requested_device),
        active_device=str(device),
        backend=backend,
        accelerator_available=accelerator_available,
        device_name=device_name,
        device_count=torch.cuda.device_count() if accelerator_available else 0,
        torch_version=torch.__version__,
        cuda_version=cuda_version,
        rocm_version=rocm_version,
    )
