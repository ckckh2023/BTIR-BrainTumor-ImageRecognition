'''任务领域的稳定词条定义'''

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    '''任务整体生命周期状态'''

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    PARTIAL = "partial"
    COMPLETED = "completed"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class JobStatus(StrEnum):
    '''RQ 作业允许写入任务元数据的状态'''

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ModelName(StrEnum):
    '''当前支持的推理模型名称'''

    CLASSIFICATION = "classification"
    SEGMENTATION = "segmentation"


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
