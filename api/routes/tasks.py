'''任务创建、推理和结果读取接口'''

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from contracts.task import (
    ClassificationData,
    ClassifyTaskResponse,
    CreateTaskRequest,
    RunTaskRequest,
    RunTaskResponse,
    SegmentTaskRequest,
    SegmentTaskResponse,
    SegmentationData,
    TaskCreatedResponse,
    TaskEnqueuedResponse,
    TaskInputData,
    TaskStatusResponse,
)
from core.settings import SETTINGS
from core.task_definitions import TaskArtifact
from repositories.task_repository import task_repository
from services.task_files import (
    create_task_dir,
    get_task_dir,
    initialize_task,
    initialize_uploaded_task,
    task_relative_path,
    validate_image_path,
)
from services.task_runner import (
    run_classification,
    run_segmentation,
    run_task_models,
)
from services.task_queue import enqueue_task_run

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


@router.post(
    "/from-path",
    response_model=TaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task_from_path(request: CreateTaskRequest) -> TaskCreatedResponse:
    '''从后端本机路径创建任务，仅用于开发调试'''
    try:
        source_image = validate_image_path(request.image_path)
        task_dir = create_task_dir(SETTINGS.output_dir)
        task_image = initialize_task(
            task_dir=task_dir,
            source_image=source_image,
            input_mode=request.input_mode,
            name=request.name,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return TaskCreatedResponse(task_id=task_dir.name, input_file=task_image.name)


@router.post("/{task_id}/classify", response_model=ClassifyTaskResponse)
def classify_task(task_id: str) -> ClassifyTaskResponse:
    '''对指定任务运行分类推理'''
    try:
        task_dir = require_task_dir(task_id)
        model_run = run_classification(task_dir)
        result = model_run.result
        task_record = task_repository.load(task_dir)
    except ValueError as exc:
        raise bad_request_http_error(exc) from exc

    prediction = result["classification"]
    return ClassifyTaskResponse(
        task_id=task_id,
        status=task_record.status,
        completed_models=[model.value for model in task_record.completed_models],
        classification=ClassificationData(
            label=prediction["class"],
            confidence=prediction["confidence"],
            probabilities=prediction["probabilities"],
        ),
        frontend_result_file=result["frontend_result_path"],
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(task_id: str) -> TaskStatusResponse:
    '''获取指定任务状态和当前结果'''
    task_dir = require_task_dir(task_id)
    task_data = task_repository.load(task_dir)

    input_data = task_data.input
    frontend_path = task_dir / TaskArtifact.FRONTEND_RESULT
    frontend_result = (
        json.loads(frontend_path.read_text(encoding="utf-8"))
        if frontend_path.is_file()
        else None
    )
    if frontend_result is not None:
        frontend_result = sanitize_public_payload(frontend_result)
        frontend_result.setdefault("image_file", Path(input_data.path).name)

    return TaskStatusResponse(
        task_id=task_data.task_id,
        name=task_data.name,
        status=task_data.status,
        created_at=task_data.created_at,
        updated_at=task_data.updated_at,
        completed_models=[model.value for model in task_data.completed_models],
        input=TaskInputData(
            filename=Path(input_data.path).name,
            storage_mode=input_data.storage_mode,
            size_bytes=input_data.size_bytes,
            sha256=input_data.sha256,
        ),
        job=(task_data.job.model_dump(mode="json") if task_data.job else None),
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


@router.post("/{task_id}/segment", response_model=SegmentTaskResponse)
def segment_task(
    task_id: str,
    request: SegmentTaskRequest,
) -> SegmentTaskResponse:
    '''对指定任务运行分割推理'''
    task_dir = require_task_dir(task_id)
    try:
        model_run = run_segmentation(task_dir, request.threshold)
        result = model_run.result
        task_record = task_repository.load(task_dir)
        mask_file = task_relative_path(task_dir, Path(result["mask_path"]))
    except ValueError as exc:
        raise bad_request_http_error(exc) from exc

    return SegmentTaskResponse(
        task_id=task_id,
        status=task_record.status,
        completed_models=[model.value for model in task_record.completed_models],
        segmentation=SegmentationData(
            threshold=result["threshold"],
            tumor_pixels=result["tumor_pixels"],
            image_pixels=result["image_pixels"],
            tumor_area_ratio=result["tumor_area_ratio"],
            mask_file=mask_file,
        ),
        frontend_result_file=result["frontend_result_path"],
    )


@router.post("/{task_id}/run", response_model=RunTaskResponse)
def run_task(
    task_id: str,
    request: RunTaskRequest | None = None,
) -> RunTaskResponse:
    '''对同一任务依次执行分类与分割'''
    task_dir = require_task_dir(task_id)
    threshold = resolve_run_threshold(request)
    try:
        run_result = run_task_models(task_dir, threshold)
        task_record = task_repository.load(task_dir)
        prediction = run_result.classification_result["classification"]
        segmentation_result = run_result.segmentation_result
        mask_file = task_relative_path(task_dir, Path(segmentation_result["mask_path"]))
    except ValueError as exc:
        raise bad_request_http_error(exc) from exc

    return RunTaskResponse(
        task_id=task_id,
        status=task_record.status,
        completed_models=[model.value for model in task_record.completed_models],
        classification=ClassificationData(
            label=prediction["class"],
            confidence=prediction["confidence"],
            probabilities=prediction["probabilities"],
        ),
        segmentation=SegmentationData(
            threshold=segmentation_result["threshold"],
            tumor_pixels=segmentation_result["tumor_pixels"],
            image_pixels=segmentation_result["image_pixels"],
            tumor_area_ratio=segmentation_result["tumor_area_ratio"],
            mask_file=mask_file,
        ),
        frontend_result_file=segmentation_result["frontend_result_path"],
    )


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
