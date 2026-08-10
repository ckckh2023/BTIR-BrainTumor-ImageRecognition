'''任务领域的稳定词条定义'''

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from types import MappingProxyType


class TaskStatus(StrEnum):
    '''任务整体生命周期状态'''

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    PARTIAL = "partial"
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


class VolumeModality(StrEnum):
    '''病例输入的固定 MRI 模态'''

    FLAIR = "flair"
    T1CE = "t1ce"
    T1 = "t1"
    T2 = "t2"


class ModelName(StrEnum):
    '''当前支持的推理模型名称'''

    CLASSIFICATION = "classification"
    SEGMENTATION = "segmentation"


ALL_MODELS = frozenset(ModelName)
VOLUME_MODALITIES = tuple(VolumeModality)
ACTIVE_ASYNC_TASK_STATUSES = frozenset(
    {
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.CANCEL_REQUESTED,
    }
)
RETRYABLE_TASK_STATUSES = frozenset({TaskStatus.FAILED})
ARCHIVABLE_TASK_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED,
        TaskStatus.CANCELED,
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
    SEGMENTATION_MASK = "prediction.nii.gz"
    PREVIEW = "preview.png"
    PREVIEW_DIRECTORY = "previews"
    ERROR = "error.json"
    LEGACY_METADATA = "task.json"


MODEL_RESULT_ARTIFACTS = MappingProxyType(
    {
        ModelName.CLASSIFICATION: TaskArtifact.CLASSIFICATION_RESULT,
        ModelName.SEGMENTATION: TaskArtifact.SEGMENTATION_RESULT,
    }
)


def model_result_filename(model_name: ModelName) -> str:
    '''返回指定模型对应的最新结果文件名'''
    return MODEL_RESULT_ARTIFACTS[model_name].value
