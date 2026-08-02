'''SQLite 中持久化的任务记录模型'''

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.task_definitions import (
    JobStatus,
    ModelName,
    TaskStatus,
)


class StoredTaskModality(BaseModel):
    """三维任务中一项模态文件的持久化信息。"""

    model_config = ConfigDict(extra="allow")

    path: str
    size_bytes: int
    sha256: str
    original_filename: str | None = None


class StoredTaskInput(BaseModel):
    '''任务创建后保存的四模态体数据摘要'''

    model_config = ConfigDict(extra="allow")

    size_bytes: int
    sha256: str
    modalities: dict[str, StoredTaskModality] | None = None


class TaskJobRecord(BaseModel):
    '''已提交到 RQ 的作业信息'''

    model_config = ConfigDict(extra="allow")

    id: str
    queue: str
    status: JobStatus
    attempt: int = 0
    max_retries: int = 0
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    queue_wait_ms: float | None = None
    execution_ms: float | None = None


class TaskRunRecord(BaseModel):
    '''单个模型的一次运行记录'''

    model_config = ConfigDict(extra="allow")

    run_id: str
    model: ModelName
    result_file: str
    created_at: datetime
    inference_ms: float | None = None


class TaskErrorRecord(BaseModel):
    '''异步作业最后一次失败信息'''

    model_config = ConfigDict(extra="allow")

    code: str = "task_failed"
    message: str
    detail: str | None = None
    updated_at: datetime


class TaskRecord(BaseModel):
    '''一条完整的任务元数据记录'''

    model_config = ConfigDict(extra="allow")

    task_id: str
    name: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    analysis_mode: Literal["3d"] = "3d"
    completed_models: list[ModelName] = Field(default_factory=list)
    input: StoredTaskInput
    job: TaskJobRecord | None = None
    runs: list[TaskRunRecord] | None = None
    error: TaskErrorRecord | None = None
