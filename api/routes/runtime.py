'''运行环境状态接口'''

from fastapi import APIRouter

from accelerator import get_runtime_status
from core.settings import SETTINGS
from contracts.task import RuntimeStatusResponse
from repositories.task_repository import (
    TaskRepositoryUnavailableError,
    task_repository,
)


router = APIRouter(tags=["运行环境"])


@router.get("/runtime", response_model=RuntimeStatusResponse)
def get_runtime() -> RuntimeStatusResponse:
    '''查看当前 PyTorch 实际使用 CPU、CUDA 还是 ROCm'''
    runtime_data = get_runtime_status(SETTINGS.device).to_dict()
    try:
        task_repository.health_check()
        task_database_available = True
    except TaskRepositoryUnavailableError:
        task_database_available = False

    return RuntimeStatusResponse(
        **runtime_data,
        task_database_backend="sqlite",
        task_database_available=task_database_available,
    )
