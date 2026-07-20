'''SQLite 中持久化的任务记录模型'''

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.task_definitions import JobStatus, ModelName, TaskStatus


class StoredTaskInput(BaseModel):
    '''任务创建后保存的输入图片信息'''

    model_config = ConfigDict(extra="allow")

    path: str
    storage_mode: str
    size_bytes: int
    sha256: str
    source_file: str | None = None
    original_filename: str | None = None


class TaskJobRecord(BaseModel):
    '''已提交到 RQ 的作业信息'''

    model_config = ConfigDict(extra="allow")

    id: str
    queue: str
    status: JobStatus
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TaskRunRecord(BaseModel):
    '''单个模型的一次运行记录'''

    model_config = ConfigDict(extra="allow")

    run_id: str
    model: ModelName
    result_file: str
    created_at: datetime


class TaskErrorRecord(BaseModel):
    '''异步作业最后一次失败信息'''

    model_config = ConfigDict(extra="allow")

    message: str
    updated_at: datetime


class TaskRecord(BaseModel):
    '''一条完整的任务元数据记录'''

    # 允许读取未来版本新增的字段，避免旧数据或滚动升级时丢失信息。
    model_config = ConfigDict(extra="allow")

    task_id: str
    name: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    completed_models: list[ModelName] = Field(default_factory=list)
    input: StoredTaskInput
    job: TaskJobRecord | None = None
    runs: list[TaskRunRecord] | None = None
    error: TaskErrorRecord | None = None
