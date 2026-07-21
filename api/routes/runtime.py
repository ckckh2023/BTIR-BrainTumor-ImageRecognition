'''运行环境状态接口'''

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError

from accelerator import get_runtime_status
from core.settings import SETTINGS
from contracts.task import RuntimeStatusResponse
from repositories.task_repository import (
    TaskRepositoryUnavailableError,
    task_repository,
)
from services.redis_client import get_redis_client


router = APIRouter(tags=["运行环境"])


@router.get("/healthz")
def get_liveness() -> dict[str, str]:
    '''进程存活检查；不依赖数据库、Redis 或模型文件'''
    return {"status": "ok"}


@router.get("/readyz")
def get_readiness() -> dict[str, object]:
    '''推理服务就绪检查；所有依赖可用时才返回 200'''
    components: dict[str, str] = {}
    try:
        task_repository.health_check()
        components["task_database"] = "ok"
    except TaskRepositoryUnavailableError:
        components["task_database"] = "unavailable"

    try:
        get_redis_client().ping()
        components["redis"] = "ok"
    except RedisError:
        components["redis"] = "unavailable"

    model_files = (
        SETTINGS.classifier_script,
        SETTINGS.classifier_model,
        SETTINGS.classifier_config,
        SETTINGS.segmenter_script,
        SETTINGS.segmenter_model,
    )
    components["models"] = "ok" if all(path.is_file() for path in model_files) else "unavailable"

    if all(component == "ok" for component in components.values()):
        return {"status": "ready", "components": components}
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"status": "not_ready", "components": components},
    )


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
