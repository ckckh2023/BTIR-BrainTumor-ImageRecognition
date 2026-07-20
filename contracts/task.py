'''用来定义任务相关的请求和响应数据模型'''


from __future__ import annotations

from pathlib import Path
from typing import Any,Literal

from pydantic import BaseModel, Field

from datetime import datetime

from core.settings import SETTINGS


# 请求模型
class CreateTaskRequest(BaseModel):
    image_path: Path = Field(description="本地 MRI 图像的绝对路径")
    name: str | None = Field(default=None, max_length=100)
    input_mode: Literal["auto", "hardlink", "copy", "reference"] = "auto"


# 响应模型
class TaskCreatedResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: Literal["created"] = "created"
    input_file: str

# 任务分类结果模型
class ClassificationData(BaseModel):
    label: Literal["yes", "no"]
    confidence: float
    probabilities: dict[str, float]

# 任务分类响应模型
class ClassifyTaskResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: Literal["partial", "completed"]
    completed_models: list[str]
    classification: ClassificationData
    frontend_result_file: str


# 任务输入数据模型
class TaskInputData(BaseModel):
    filename: str
    storage_mode: str
    size_bytes: int
    sha256: str


class TaskJobData(BaseModel):
    id: str
    queue: str
    status: Literal["queued", "running", "succeeded", "failed"]
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


# 任务状态响应模型
class TaskStatusResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    name: str
    status: Literal[
        "created", "queued", "running", "partial", "completed", "succeeded", "failed"
    ]
    created_at: datetime
    updated_at: datetime
    completed_models: list[str]
    input: TaskInputData
    job: TaskJobData | None = None
    frontend_result: dict[str, Any] | None = None


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


# 任务分割请求模型
class SegmentTaskRequest(BaseModel):
    threshold: float = Field(
        default=SETTINGS.default_segment_threshold,
        ge=0.0,
        le=1.0,
    )


# 任务分割结果模型
class SegmentationData(BaseModel):
    threshold: float
    tumor_pixels: int
    image_pixels: int
    tumor_area_ratio: float
    mask_file: str


# 任务分割响应模型
class SegmentTaskResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: Literal["partial", "completed"]
    completed_models: list[str]
    segmentation: SegmentationData
    frontend_result_file: str


# 任务运行请求模型
class RunTaskRequest(BaseModel):
    threshold: float = Field(
        default=SETTINGS.default_segment_threshold,
        ge=0.0,
        le=1.0,
    )


# 任务运行响应模型
class RunTaskResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: Literal["partial", "completed"]
    completed_models: list[str]
    classification: ClassificationData
    segmentation: SegmentationData
    frontend_result_file: str


class TaskEnqueuedResponse(BaseModel):
    schema_version: Literal["0.1"] = "0.1"
    task_id: str
    status: Literal["queued", "running"]
    job: TaskJobData
    reused_existing_job: bool
