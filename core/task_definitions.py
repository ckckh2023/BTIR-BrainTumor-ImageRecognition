'''任务领域的稳定词条定义'''

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class TaskStatus(StrEnum):
    '''任务整体生命周期状态'''

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    PARTIAL = "partial"
    # 保留旧任务记录的兼容性；新任务完成统一使用 SUCCEEDED
    COMPLETED = "completed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class JobStatus(StrEnum):
    '''RQ 作业允许写入任务元数据的状态'''

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class ModelName(StrEnum):
    '''当前支持的推理模型名称'''

    CLASSIFICATION = "classification"
    SEGMENTATION = "segmentation"


ALL_MODELS = frozenset(ModelName)
ACTIVE_ASYNC_TASK_STATUSES = frozenset(
    {
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.CANCEL_REQUESTED,
    }
)


def task_status_from_job_status(status: JobStatus | str) -> TaskStatus:
    '''将队列作业状态显式映射为任务状态'''
    try:
        job_status = JobStatus(status)
    except ValueError as exc:
        raise ValueError(f"不支持的异步任务状态：{status}") from exc
    return TaskStatus(job_status.value)


def task_status_for_completed_models(
    models: Iterable[ModelName | str],
) -> TaskStatus:
    '''根据已完成模型计算同步任务的终态'''
    completed_models = {ModelName(model) for model in models}
    return (
        TaskStatus.SUCCEEDED
        if ALL_MODELS <= completed_models
        else TaskStatus.PARTIAL
    )


class InputStorageMode(StrEnum):
    '''创建任务时保存输入图片的方式'''

    AUTO = "auto"
    HARDLINK = "hardlink"
    COPY = "copy"
    REFERENCE = "reference"


class TaskDirectory(StrEnum):
    '''任务目录中的固定子目录名'''

    INPUT = "input"
    RUNS = "runs"


class TaskArtifact(StrEnum):
    '''任务目录中的固定结果文件名'''

    CLASSIFICATION_RESULT = "classification.json"
    SEGMENTATION_RESULT = "segmentation.json"
    FRONTEND_RESULT = "frontend_result.json"
    RUN_RESULT = "result.json"
    LEGACY_METADATA = "task.json"


def model_result_filename(model_name: ModelName) -> str:
    '''返回指定模型对应的最新结果文件名'''
    return f"{model_name.value}.json"
