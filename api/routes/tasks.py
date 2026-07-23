'''任务创建、推理和结果读取接口'''

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from contracts.task import (
    RunTaskRequest,
    TaskCreatedResponse,
    TaskCancellationResponse,
    TaskEnqueuedResponse,
    TaskErrorData,
    TaskInputData,
    TaskListResponse,
    TaskStatusResponse,
    TaskSummaryResponse,
)
from core.settings import SETTINGS
from core.task_definitions import TaskArtifact, TaskStatus
from repositories.task_repository import task_repository
from services.task_files import (
    create_task_dir,
    get_task_dir,
    initialize_uploaded_task,
)
from services.task_queue import cancel_task_run, enqueue_task_run, reconcile_task_job

router = APIRouter(prefix="/tasks", tags=["任务"])

PRIVATE_PATH_FIELDS = {
    "frontend_result_path",
    "history_result_path",
    "image_path",
    "mask_path",
    "model_result_path",
    "path",
    "source_path",
    "task_dir",
}


def sanitize_public_payload(value):
    '''移除结果 JSON 中可能存在的本机路径字段'''
    if isinstance(value, dict):
        return {
            key: sanitize_public_payload(item)
            for key, item in value.items()
            if key not in PRIVATE_PATH_FIELDS
        }
    if isinstance(value, list):
        return [sanitize_public_payload(item) for item in value]
    return value


def require_task_dir(task_id: str) -> Path:
    '''获取指定任务目录，不存在时返回 HTTP 404'''
    try:
        return get_task_dir(SETTINGS.output_dir, task_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc


def resolve_run_threshold(request: RunTaskRequest | None) -> float:
    '''读取请求阈值；省略请求体时使用项目默认值'''
    return (
        request.threshold
        if request is not None
        else SETTINGS.default_segment_threshold
    )


def bad_request_http_error(exc: ValueError) -> HTTPException:
    '''将预期的业务校验错误转换为 HTTP 400'''
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def task_input_data(task_data) -> TaskInputData:
    input_data = task_data.input
    return TaskInputData(
        filename=Path(input_data.path).name,
        storage_mode=input_data.storage_mode,
        size_bytes=input_data.size_bytes,
        sha256=input_data.sha256,
    )


def task_error_data(task_data) -> TaskErrorData | None:
    if task_data.error is None:
        return None
    return TaskErrorData(
        code=task_data.error.code,
        message=task_data.error.message,
        updated_at=task_data.error.updated_at,
    )


def task_common_data(task_data) -> dict[str, Any]:
    '''组装任务列表与详情接口共享的公开字段'''
    return {
        "task_id": task_data.task_id,
        "name": task_data.name,
        "status": task_data.status,
        "created_at": task_data.created_at,
        "updated_at": task_data.updated_at,
        "completed_models": [model.value for model in task_data.completed_models],
        "input": task_input_data(task_data),
        "job": task_data.job.model_dump(mode="json") if task_data.job else None,
        "error": task_error_data(task_data),
    }


def task_summary_data(task_data) -> TaskSummaryResponse:
    return TaskSummaryResponse(**task_common_data(task_data))


@router.post(
    "",
    response_model=TaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_from_upload(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> TaskCreatedResponse:
    '''上传图片并创建任务'''
    task_dir: Path | None = None
    try:
        task_dir = create_task_dir(SETTINGS.output_dir)
        task_image = initialize_uploaded_task(
            task_dir=task_dir,
            upload=file.file,
            filename=file.filename,
            name=name,
        )
    except ValueError as exc:
        if task_dir is not None:
            shutil.rmtree(task_dir, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return TaskCreatedResponse(task_id=task_dir.name, input_file=task_image.name)


@router.get("", response_model=TaskListResponse)
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
) -> TaskListResponse:
    '''分页查询任务，可按整体状态筛选'''
    task_records, total = task_repository.list_tasks(
        limit=limit,
        offset=offset,
        status=status_filter,
    )
    return TaskListResponse(
        items=[task_summary_data(record) for record in task_records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str) -> TaskStatusResponse:
    '''获取指定任务状态和当前结果'''
    task_dir = require_task_dir(task_id)
    task_data = reconcile_task_job(task_dir)

    frontend_path = task_dir / TaskArtifact.FRONTEND_RESULT
    frontend_result = (
        json.loads(frontend_path.read_text(encoding="utf-8"))
        if frontend_path.is_file()
        else None
    )
    if frontend_result is not None:
        frontend_result = sanitize_public_payload(frontend_result)
        frontend_result.setdefault("image_file", Path(task_data.input.path).name)

    return TaskStatusResponse(
        **task_common_data(task_data),
        frontend_result=frontend_result,
    )


@router.get("/{task_id}/files/{file_path:path}")
def get_task_file(task_id: str, file_path: str) -> FileResponse:
    '''安全读取任务目录中的结果文件'''
    task_dir = require_task_dir(task_id)
    try:
        file = (task_dir / file_path).resolve()
        file.relative_to(task_dir.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务文件不存在",
        ) from exc

    if not file.is_file() or file.name == TaskArtifact.LEGACY_METADATA:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务文件不存在",
        )

    if file.suffix.lower() == ".json":
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务文件不存在",
            ) from exc
        return JSONResponse(sanitize_public_payload(data))

    return FileResponse(file, filename=file.name)


@router.post(
    "/{task_id}/run-async",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_task(
    task_id: str,
    request: RunTaskRequest | None = None,
) -> TaskEnqueuedResponse:
    '''将完整推理提交到 RQ 队列，并立即返回作业信息'''
    task_dir = require_task_dir(task_id)
    threshold = resolve_run_threshold(request)
    try:
        job, reused = enqueue_task_run(task_dir, threshold)
    except ValueError as exc:
        raise bad_request_http_error(exc) from exc

    return TaskEnqueuedResponse(
        task_id=task_id,
        status=job["status"],
        job=job,
        reused_existing_job=reused,
    )


@router.post("/{task_id}/cancel", response_model=TaskCancellationResponse)
def cancel_task(task_id: str) -> TaskCancellationResponse:
    '''取消排队任务，或请求运行中的任务在安全阶段停止'''
    task_dir = require_task_dir(task_id)
    try:
        task_record = cancel_task_run(task_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return TaskCancellationResponse(
        task_id=task_id,
        status=task_record.status,
    )


@router.post(
    "/{task_id}/retry",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_failed_task(
    task_id: str,
    request: RunTaskRequest | None = None,
) -> TaskEnqueuedResponse:
    '''手动重新提交一项最终失败的推理任务'''
    task_dir = require_task_dir(task_id)
    threshold = resolve_run_threshold(request)
    try:
        job, reused = enqueue_task_run(
            task_dir,
            threshold,
            retry_failed_only=True,
        )
    except ValueError as exc:
        raise bad_request_http_error(exc) from exc

    return TaskEnqueuedResponse(
        task_id=task_id,
        status=job["status"],
        job=job,
        reused_existing_job=reused,
    )
