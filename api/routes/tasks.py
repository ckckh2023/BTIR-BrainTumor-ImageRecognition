'''任务创建、推理和结果读取接口'''

from __future__ import annotations

import json
import shutil
import zipfile
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse

from api.auth import require_password_changed
from contracts.task import (
    ArchivedTaskListResponse,
    ArchivedTaskSummaryResponse,
    TaskArchivedResponse,
    TaskCancellationResponse,
    TaskEnqueuedResponse,
    TaskErrorData,
    TaskFollowUpHistoryItem,
    TaskFollowUpResponse,
    TaskInputFileData,
    TaskInputData,
    TaskListResponse,
    TaskRunListResponse,
    TaskRunSummaryResponse,
    TaskPurgedResponse,
    TaskRestoredResponse,
    TaskStatusResponse,
    TaskSummaryResponse,
    VolumeTaskCreatedResponse,
)
from core.settings import SETTINGS
from core.task_definitions import (
    ACTIVE_ASYNC_TASK_STATUSES,
    ModelName,
    TaskArtifact,
    TaskStatus,
    VOLUME_MODALITIES,
)
from core.user_records import UserRecord
from repositories.task_repository import task_repository
from repositories.task_repository_contracts import (
    TaskNotFoundError,
    TaskQuotaExceededError,
)
from services.archive_service import archive_task, purge_archived_task, restore_task
from services.dicom_conversion import (
    DICOMSeriesSelectionRequired,
    initialize_uploaded_dicom_task,
)
from services.task_files import (
    create_task_dir,
    get_task_dir,
    initialize_uploaded_volume_task,
    select_volume_archive_entries,
    volume_modality_from_filename,
    VolumeArchiveSelectionRequired,
)
from services.task_queue import (
    cancel_task_run,
    enqueue_task_run,
    get_task_job_progress,
    reconcile_task_job,
)
from services.task_lock import user_quota_lock

router = APIRouter(prefix="/tasks", tags=["任务"])

PRIVATE_JSON_FIELDS = {
    "detail",
    "frontend_result_path",
    "history_result_path",
    "image_path",
    "mask_path",
    "model_result_path",
    "path",
    "source_path",
    "task_dir",
    "traceback",
}
PRIVATE_TASK_FILENAMES = {TaskArtifact.LEGACY_METADATA, TaskArtifact.ERROR}


def sanitize_public_payload(value):
    '''移除结果 JSON 中可能暴露服务端路径或诊断信息的字段'''
    if isinstance(value, dict):
        return {
            key: sanitize_public_payload(item)
            for key, item in value.items()
            if key not in PRIVATE_JSON_FIELDS
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


def verify_task_owner(task_id: str, user: UserRecord) -> None:
    '''严格验证任务归属；不存在、未分配或越权时统一返回 404'''
    try:
        owner_id = task_repository.get_task_user_id(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    if owner_id != user.user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )


def enforce_task_storage_limit(user: UserRecord) -> None:
    if task_repository.count(user_id=user.user_id) >= SETTINGS.max_tasks_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前账号保存的任务数已达到上限，请先归档并等待管理员清理",
        )


def discard_incomplete_task_dir(task_dir: Path | None) -> None:
    '''清理创建后但未成功初始化的任务目录'''
    if task_dir is not None:
        shutil.rmtree(task_dir, ignore_errors=True)


def enforce_active_task_limit(task_id: str, user: UserRecord) -> None:
    active_tasks = task_repository.list_active_tasks(
        limit=SETTINGS.max_active_tasks_per_user + 1,
        user_id=user.user_id,
    )
    if any(task.task_id == task_id for task in active_tasks):
        return
    if len(active_tasks) >= SETTINGS.max_active_tasks_per_user:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="当前账号同时排队或运行的任务数已达到上限",
        )


def bad_request_http_error(exc: ValueError) -> HTTPException:
    '''将预期的业务校验错误转换为 HTTP 400'''
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def normalize_query_datetime(value: datetime | None) -> datetime | None:
    '''将查询时间统一为 UTC；未携带时区时按 UTC 处理'''
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def task_input_data(task_data) -> TaskInputData:
    input_data = task_data.input
    modality_files = {
        modality: TaskInputFileData(
            filename=Path(file_data.path).name,
            size_bytes=file_data.size_bytes,
            sha256=file_data.sha256,
        )
        for modality, file_data in (input_data.modalities or {}).items()
    }
    return TaskInputData(
        size_bytes=input_data.size_bytes,
        sha256=input_data.sha256,
        files=modality_files,
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
        "case_id": task_data.case_id,
        "case_name": task_data.case_name,
        "study_date": task_data.study_date,
        "analysis_mode": task_data.analysis_mode,
        "completed_models": [model.value for model in task_data.completed_models],
        "input": task_input_data(task_data),
        "job": task_data.job.model_dump(mode="json") if task_data.job else None,
        "error": task_error_data(task_data),
    }


def task_summary_data(task_data) -> TaskSummaryResponse:
    return TaskSummaryResponse(**task_common_data(task_data))


def archived_task_summary_data(task_data) -> ArchivedTaskSummaryResponse:
    archived_at = task_data.archived_at
    if archived_at is None:
        raise ValueError("任务缺少归档时间")
    return ArchivedTaskSummaryResponse(
        **task_common_data(task_data),
        archived_at=archived_at,
        purge_eligible_at=archived_at
        + timedelta(days=SETTINGS.task_archive_grace_days),
    )


@router.post(
    "/3d",
    response_model=VolumeTaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_3d_task_from_upload(
    flair: UploadFile = File(...),
    t1ce: UploadFile = File(...),
    t1: UploadFile = File(...),
    t2: UploadFile = File(...),
    name: str | None = Form(default=None),
    case_id: str | None = Form(default=None, max_length=128),
    case_name: str | None = Form(default=None, max_length=100),
    study_date: date | None = Form(default=None),
    current_user: UserRecord = Depends(require_password_changed),
) -> VolumeTaskCreatedResponse:
    '''上传四模态 NIfTI 并创建 3D 分割任务'''

    enforce_task_storage_limit(current_user)
    task_dir: Path | None = None
    uploads = {
        "flair": flair,
        "t1ce": t1ce,
        "t1": t1,
        "t2": t2,
    }
    try:
        task_dir = create_task_dir(SETTINGS.output_dir)
        stored_files = initialize_uploaded_volume_task(
            task_dir=task_dir,
            uploads={
                modality: upload.file
                for modality, upload in uploads.items()
            },
            filenames={
                modality: upload.filename
                for modality, upload in uploads.items()
            },
            name=name,
            case_id=case_id,
            case_name=case_name,
            study_date=study_date,
            user_id=current_user.user_id,
            max_tasks_per_user=SETTINGS.max_tasks_per_user,
        )
    except TaskQuotaExceededError as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return VolumeTaskCreatedResponse(
        task_id=task_dir.name,
        case_id=case_id or task_dir.name,
        input_files={
            modality: path.name
            for modality, path in stored_files.items()
        },
    )


@router.post(
    "/3d/dicom",
    response_model=VolumeTaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_3d_task_from_dicom(
    files: list[UploadFile] = File(...),
    name: str | None = Form(default=None),
    case_id: str | None = Form(default=None, max_length=128),
    case_name: str | None = Form(default=None, max_length=100),
    study_date: date | None = Form(default=None),
    flair_series_uid: str | None = Form(default=None),
    t1ce_series_uid: str | None = Form(default=None),
    t1_series_uid: str | None = Form(default=None),
    t2_series_uid: str | None = Form(default=None),
    current_user: UserRecord = Depends(require_password_changed),
) -> VolumeTaskCreatedResponse:
    '''上传一个病例的 DICOM 文件夹并转换为四模态 NIfTI'''

    enforce_task_storage_limit(current_user)
    task_dir: Path | None = None
    try:
        task_dir = create_task_dir(SETTINGS.output_dir)
        stored_files = initialize_uploaded_dicom_task(
            task_dir=task_dir,
            uploads=[
                (upload.filename or f"dicom-{index}", upload.file)
                for index, upload in enumerate(files, 1)
                if upload.filename
            ],
            name=name,
            case_id=case_id,
            case_name=case_name,
            study_date=study_date,
            user_id=current_user.user_id,
            max_tasks_per_user=SETTINGS.max_tasks_per_user,
            selected_series_uids={
                "flair": flair_series_uid,
                "t1ce": t1ce_series_uid,
                "t1": t1_series_uid,
                "t2": t2_series_uid,
            },
        )
    except TaskQuotaExceededError as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except DICOMSeriesSelectionRequired as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "dicom_series_selection_required",
                "message": str(exc),
                "modalities": exc.modalities,
            },
        ) from exc
    except (RuntimeError, ValueError) as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return VolumeTaskCreatedResponse(
        task_id=task_dir.name,
        case_id=case_id or task_dir.name,
        input_files={
            modality: path.name
            for modality, path in stored_files.items()
        },
    )


def _iter_archive_dicom_uploads(archive: zipfile.ZipFile):
    '''逐个打开 ZIP 内的 DICOM，避免同时占用过多文件句柄'''

    for entry in archive.infolist():
        if entry.is_dir():
            continue
        with archive.open(entry) as stream:
            yield entry.filename, stream


@router.post(
    "/3d/archive",
    response_model=VolumeTaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_3d_task_from_archive(
    archive: UploadFile = File(...),
    name: str | None = Form(default=None),
    case_id: str | None = Form(default=None, max_length=128),
    case_name: str | None = Form(default=None, max_length=100),
    study_date: date | None = Form(default=None),
    flair: UploadFile | None = File(default=None),
    t1ce: UploadFile | None = File(default=None),
    t1: UploadFile | None = File(default=None),
    t2: UploadFile | None = File(default=None),
    flair_entry: str | None = Form(default=None),
    t1ce_entry: str | None = Form(default=None),
    t1_entry: str | None = Form(default=None),
    t2_entry: str | None = Form(default=None),
    flair_series_uid: str | None = Form(default=None),
    t1ce_series_uid: str | None = Form(default=None),
    t1_series_uid: str | None = Form(default=None),
    t2_series_uid: str | None = Form(default=None),
    current_user: UserRecord = Depends(require_password_changed),
) -> VolumeTaskCreatedResponse:
    '''上传病例 ZIP，自动识别四模态 NIfTI 或 DICOM 序列'''

    archive_name = Path(archive.filename or "").name
    if not archive_name.lower().endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 .zip 压缩包",
        )
    if archive.size is not None and archive.size > SETTINGS.max_3d_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="压缩包大小超过上传限制",
        )

    enforce_task_storage_limit(current_user)
    task_dir: Path | None = None
    try:
        with zipfile.ZipFile(archive.file) as uploaded_archive, ExitStack() as streams:
            archive_has_nifti = any(
                volume_modality_from_filename(Path(entry.filename).name) is not None
                for entry in uploaded_archive.infolist()
                if not entry.is_dir()
            )
            manual_uploads = {
                modality: upload
                for modality, upload in {
                    "flair": flair,
                    "t1ce": t1ce,
                    "t1": t1,
                    "t2": t2,
                }.items()
                if upload is not None and upload.filename
            }
            task_dir = create_task_dir(SETTINGS.output_dir)
            if archive_has_nifti or set(manual_uploads) == set(VOLUME_MODALITIES):
                entries = select_volume_archive_entries(
                    uploaded_archive,
                    selected_filenames={
                        "flair": flair_entry,
                        "t1ce": t1ce_entry,
                        "t1": t1_entry,
                        "t2": t2_entry,
                    },
                    required_modalities=set(VOLUME_MODALITIES) - set(manual_uploads),
                )
                stored_files = initialize_uploaded_volume_task(
                    task_dir=task_dir,
                    uploads={
                        modality: (
                            manual_uploads[modality].file
                            if modality in manual_uploads
                            else streams.enter_context(uploaded_archive.open(entries[modality]))
                        )
                        for modality in VOLUME_MODALITIES
                    },
                    filenames={
                        modality: (
                            manual_uploads[modality].filename
                            if modality in manual_uploads
                            else entries[modality].filename
                        )
                        for modality in VOLUME_MODALITIES
                    },
                    name=name,
                    case_id=case_id,
                    case_name=case_name,
                    study_date=study_date,
                    user_id=current_user.user_id,
                    max_tasks_per_user=SETTINGS.max_tasks_per_user,
                )
            elif manual_uploads:
                raise ValueError("DICOM 压缩包不能与单个 NIfTI 文件混合上传")
            else:
                stored_files = initialize_uploaded_dicom_task(
                    task_dir=task_dir,
                    uploads=_iter_archive_dicom_uploads(uploaded_archive),
                    name=name,
                    case_id=case_id,
                    case_name=case_name,
                    study_date=study_date,
                    user_id=current_user.user_id,
                    max_tasks_per_user=SETTINGS.max_tasks_per_user,
                    selected_series_uids={
                        "flair": flair_series_uid,
                        "t1ce": t1ce_series_uid,
                        "t1": t1_series_uid,
                        "t2": t2_series_uid,
                    },
                )
    except TaskQuotaExceededError as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except VolumeArchiveSelectionRequired as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "archive_modality_selection_required",
                "message": str(exc),
                "modalities": exc.modalities,
            },
        ) from exc
    except DICOMSeriesSelectionRequired as exc:
        discard_incomplete_task_dir(task_dir)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "dicom_series_selection_required",
                "message": str(exc),
                "modalities": exc.modalities,
            },
        ) from exc
    except RuntimeError as exc:
        discard_incomplete_task_dir(task_dir)
        message = str(exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                message
                if "DICOM" in message
                else "压缩包中的文件无法读取，请使用未加密的标准 ZIP 文件"
            ),
        ) from exc
    except (ValueError, zipfile.BadZipFile) as exc:
        discard_incomplete_task_dir(task_dir)
        message = str(exc) or "压缩包格式无效"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message,
        ) from exc

    return VolumeTaskCreatedResponse(
        task_id=task_dir.name,
        case_id=case_id or task_dir.name,
        input_files={
            modality: path.name
            for modality, path in stored_files.items()
        },
    )


@router.get("", response_model=TaskListResponse)
def list_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None, alias="q", max_length=100),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskListResponse:
    '''分页查询任务，可按整体状态筛选'''
    normalized_from = normalize_query_datetime(created_from)
    normalized_to = normalize_query_datetime(created_to)
    if (
        normalized_from is not None
        and normalized_to is not None
        and normalized_from > normalized_to
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="created_from 不能晚于 created_to",
        )

    task_records, total = task_repository.list_tasks(
        limit=limit,
        offset=offset,
        status=status_filter,
        query=query.strip() if query and query.strip() else None,
        created_from=normalized_from,
        created_to=normalized_to,
        user_id=current_user.user_id,
    )
    return TaskListResponse(
        items=[task_summary_data(record) for record in task_records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/archived", response_model=ArchivedTaskListResponse)
def list_archived_tasks(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    query: str | None = Query(default=None, alias="q", max_length=100),
    current_user: UserRecord = Depends(require_password_changed),
) -> ArchivedTaskListResponse:
    '''分页查询尚未永久清除的归档任务'''
    task_records, total = task_repository.list_archived_tasks(
        limit=limit,
        offset=offset,
        status=status_filter,
        query=query.strip() if query and query.strip() else None,
        user_id=current_user.user_id,
    )
    return ArchivedTaskListResponse(
        items=[archived_task_summary_data(record) for record in task_records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}", response_model=TaskStatusResponse)
def get_task(
    task_id: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskStatusResponse:
    '''获取指定任务状态和当前结果'''
    try:
        task_data = task_repository.load_for_user(task_id, current_user.user_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    task_dir = require_task_dir(task_id)
    task_data = reconcile_task_job(task_dir, record=task_data)

    frontend_path = task_dir / TaskArtifact.FRONTEND_RESULT
    frontend_result = None
    if (
        task_data.status not in ACTIVE_ASYNC_TASK_STATUSES
        and frontend_path.is_file()
    ):
        frontend_result = json.loads(frontend_path.read_text(encoding="utf-8"))
    if frontend_result is not None:
        frontend_result = sanitize_public_payload(frontend_result)

    progress = (
        get_task_job_progress(task_data)
        if task_data.status in ACTIVE_ASYNC_TASK_STATUSES
        else None
    )
    return TaskStatusResponse(
        **task_common_data(task_data),
        frontend_result=frontend_result,
        progress=progress["progress"] if progress else None,
        progress_stage=progress["progress_stage"] if progress else None,
    )


@router.get("/{task_id}/follow-up", response_model=TaskFollowUpResponse)
def get_task_follow_up(
    task_id: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskFollowUpResponse:
    '''返回同一病例中日期最近的已完成检查结果'''
    try:
        current = task_repository.load_for_user(task_id, current_user.user_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc

    response = TaskFollowUpResponse(
        task_id=current.task_id,
        case_id=current.case_id,
        case_name=current.case_name,
        study_date=current.study_date,
    )
    if not current.case_id:
        return response

    records, _ = task_repository.list_tasks(
        limit=SETTINGS.max_tasks_per_user,
        offset=0,
        user_id=current_user.user_id,
    )
    candidates = [
        record
        for record in records
        if (
            record.task_id != current.task_id
            and record.case_id == current.case_id
            and record.created_at < current.created_at
            and record.status in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL}
        )
    ]
    for baseline in sorted(
        candidates,
        key=lambda record: (record.study_date or record.created_at.date(), record.created_at),
        reverse=True,
    ):
        frontend_path = require_task_dir(baseline.task_id) / TaskArtifact.FRONTEND_RESULT
        if not frontend_path.is_file():
            continue
        frontend_result = sanitize_public_payload(
            json.loads(frontend_path.read_text(encoding="utf-8"))
        )
        history_item = TaskFollowUpHistoryItem(
            task=task_summary_data(baseline),
            frontend_result=frontend_result,
        )
        response.history.append(history_item)

    if response.history:
        response.baseline = response.history[0].task
        response.baseline_frontend_result = response.history[0].frontend_result
    return response


@router.delete("/{task_id}", response_model=TaskArchivedResponse)
def delete_task(
    task_id: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskArchivedResponse:
    '''将指定的非活动任务安全移入归档区'''
    verify_task_owner(task_id, current_user)
    try:
        task_data = archive_task(
            task_id,
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    archived_at = task_data.archived_at
    if archived_at is None:
        raise RuntimeError("任务归档完成但缺少归档时间")
    return TaskArchivedResponse(
        task_id=task_id,
        archived_at=archived_at,
        purge_eligible_at=archived_at
        + timedelta(days=SETTINGS.task_archive_grace_days),
    )


@router.post("/{task_id}/restore", response_model=TaskRestoredResponse)
def restore_archived_task(
    task_id: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskRestoredResponse:
    '''将尚未永久清除的归档任务恢复到活动任务目录'''
    verify_task_owner(task_id, current_user)
    try:
        task_data = restore_task(
            task_id,
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return TaskRestoredResponse(
        task_id=task_id,
        task_status=task_data.status,
        restored_at=task_data.updated_at,
    )


@router.delete("/{task_id}/purge", response_model=TaskPurgedResponse)
def purge_archived_task_endpoint(
    task_id: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskPurgedResponse:
    '''彻底删除一项已归档任务'''
    verify_task_owner(task_id, current_user)
    try:
        purge_archived_task(
            task_id,
            actor_user_id=current_user.user_id,
            target_user_id=current_user.user_id,
        )
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="归档任务不存在",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return TaskPurgedResponse(task_id=task_id, purged_at=datetime.now().astimezone())


@router.get("/{task_id}/runs", response_model=TaskRunListResponse)
def list_task_runs(
    task_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    model_filter: ModelName | None = Query(default=None, alias="model"),
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskRunListResponse:
    '''分页查询指定任务的历史运行元数据'''
    try:
        task_data = task_repository.load_for_user(task_id, current_user.user_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    task_dir = require_task_dir(task_id)
    runs = task_data.runs or []
    if model_filter is not None:
        runs = [run for run in runs if run.model == model_filter]
    runs = sorted(runs, key=lambda run: (run.created_at, run.run_id), reverse=True)
    page = runs[offset : offset + limit]

    return TaskRunListResponse(
        task_id=task_id,
        items=[
            TaskRunSummaryResponse(
                run_id=run.run_id,
                model=run.model,
                created_at=run.created_at,
                inference_ms=run.inference_ms,
            )
            for run in page
        ],
        total=len(runs),
        limit=limit,
        offset=offset,
    )


@router.get("/{task_id}/files/{file_path:path}")
def get_task_file(
    task_id: str,
    file_path: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> FileResponse:
    '''安全读取任务目录中的结果文件'''
    verify_task_owner(task_id, current_user)
    task_dir = require_task_dir(task_id)
    try:
        file = (task_dir / file_path).resolve()
        file.relative_to(task_dir.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务文件不存在",
        ) from exc

    if not file.is_file() or file.name in PRIVATE_TASK_FILENAMES:
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
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskEnqueuedResponse:
    '''将完整推理提交到 RQ 队列，并立即返回作业信息'''
    verify_task_owner(task_id, current_user)
    task_dir = require_task_dir(task_id)
    with user_quota_lock(current_user.user_id):
        enforce_active_task_limit(task_id, current_user)
        try:
            job, reused = enqueue_task_run(task_dir)
        except ValueError as exc:
            raise bad_request_http_error(exc) from exc

    return TaskEnqueuedResponse(
        task_id=task_id,
        status=job["status"],
        job=job,
        reused_existing_job=reused,
    )


@router.post("/{task_id}/cancel", response_model=TaskCancellationResponse)
def cancel_task(
    task_id: str,
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskCancellationResponse:
    '''取消排队任务，或请求运行中的任务在安全阶段停止'''
    verify_task_owner(task_id, current_user)
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
    current_user: UserRecord = Depends(require_password_changed),
) -> TaskEnqueuedResponse:
    '''手动重新提交一项最终失败的推理任务'''
    verify_task_owner(task_id, current_user)
    task_dir = require_task_dir(task_id)
    with user_quota_lock(current_user.user_id):
        enforce_active_task_limit(task_id, current_user)
        try:
            job, reused = enqueue_task_run(
                task_dir,
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
