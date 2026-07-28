'''用来定义任务相关的请求和响应数据模型'''


from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from datetime import datetime

from core.settings import SETTINGS
from core.task_definitions import JobStatus, ModelName, TaskStatus


# 响应模型
class TaskCreatedResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: TaskStatus = TaskStatus.CREATED
    input_file: str

# 任务输入数据模型
class TaskInputData(BaseModel):
    filename: str
    storage_mode: str
    size_bytes: int
    sha256: str


class TaskJobData(BaseModel):
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


class TaskErrorData(BaseModel):
    code: str
    message: str
    updated_at: datetime


# 任务状态响应模型
class TaskStatusResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    name: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    completed_models: list[str]
    input: TaskInputData
    job: TaskJobData | None = None
    error: TaskErrorData | None = None
    frontend_result: dict[str, Any] | None = None


class TaskSummaryResponse(BaseModel):
    task_id: str
    name: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    completed_models: list[str]
    input: TaskInputData
    job: TaskJobData | None = None
    error: TaskErrorData | None = None


class TaskListResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    items: list[TaskSummaryResponse]
    total: int
    limit: int
    offset: int


class TaskRunSummaryResponse(BaseModel):
    run_id: str
    model: ModelName
    created_at: datetime
    inference_ms: float | None = None


class TaskRunListResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    items: list[TaskRunSummaryResponse]
    total: int
    limit: int
    offset: int


class RuntimeStatusResponse(BaseModel):
    '''当前后端实际使用的推理设备'''

    schema_version: Literal["0.1"] = "0.1"
    requested_device: str
    active_device: str
    backend: Literal["cpu", "cuda", "rocm"]
    accelerator_available: bool
    device_name: str | None
    device_count: int
    torch_version: str
    cuda_version: str | None
    rocm_version: str | None
    task_database_backend: Literal["sqlite"]
    task_database_available: bool


class InferenceQueueStatusResponse(BaseModel):
    '''推理队列的只读运行状态'''

    schema_version: Literal["0.1"] = "0.1"
    active_workers: int
    queued_jobs: int
    running_jobs: int
    failed_jobs: int
    oldest_wait_seconds: float | None = None


# 任务运行请求模型
class RunTaskRequest(BaseModel):
    threshold: float = Field(
        default=SETTINGS.default_segment_threshold,
        ge=0.0,
        le=1.0,
    )


class TaskEnqueuedResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: JobStatus
    job: TaskJobData
    reused_existing_job: bool


class TaskCancellationResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: TaskStatus
