'''运行环境状态接口'''

from fastapi import APIRouter, HTTPException, status
from redis.exceptions import RedisError

from accelerator import get_runtime_status
from core.settings import SETTINGS
from core.task_definitions import AnalysisMode
from contracts.task import InferenceQueueStatusResponse, RuntimeStatusResponse
from repositories.task_repository_contracts import (
    TaskRepositoryUnavailableError,
)
from repositories.task_repository import task_repository
from services.redis_client import get_redis_client
from services.task_queue import (
    get_inference_queue_status,
    has_active_inference_worker,
)


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

    if components["redis"] == "ok":
        try:
            components["inference_worker_2d"] = (
                "ok"
                if has_active_inference_worker(AnalysisMode.TWO_D)
                else "unavailable"
            )
            components["inference_worker_3d"] = (
                "ok"
                if has_active_inference_worker(AnalysisMode.THREE_D)
                else "unavailable"
            )
        except RedisError:
            components["inference_worker_2d"] = "unavailable"
            components["inference_worker_3d"] = "unavailable"
    else:
        components["inference_worker_2d"] = "unavailable"
        components["inference_worker_3d"] = "unavailable"

    model_files = (
        SETTINGS.classifier_script,
        SETTINGS.classifier_model,
        SETTINGS.classifier_config,
        SETTINGS.segmenter_script,
        SETTINGS.segmenter_model,
        SETTINGS.segmenter_3d_script,
        SETTINGS.segmenter_3d_model,
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


@router.get("/ops/queue", response_model=InferenceQueueStatusResponse)
def get_queue_status() -> InferenceQueueStatusResponse:
    '''获取推理队列的只读运维状态'''
    try:
        return InferenceQueueStatusResponse(**get_inference_queue_status())
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redis 队列不可用，无法读取队列状态",
        ) from exc
