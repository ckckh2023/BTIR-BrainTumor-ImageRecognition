'''运行环境状态接口'''

from fastapi import APIRouter

from accelerator import get_runtime_status
from core.settings import SETTINGS
from contracts.task import RuntimeStatusResponse


router = APIRouter(tags=["运行环境"])


@router.get("/runtime", response_model=RuntimeStatusResponse)
def get_runtime() -> RuntimeStatusResponse:
    '''查看当前 PyTorch 实际使用 CPU、CUDA 还是 ROCm'''
    return RuntimeStatusResponse(**get_runtime_status(SETTINGS.device).to_dict())
