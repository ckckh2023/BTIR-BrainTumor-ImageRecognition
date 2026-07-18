'''统一管理 CPU、CUDA 与 ROCm 推理设备'''

from accelerator.runtime import get_runtime_status, resolve_device, validate_device

__all__ = ["get_runtime_status", "resolve_device", "validate_device"]
