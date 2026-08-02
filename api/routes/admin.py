'''管理员只读查询接口'''

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import get_user_repository, require_admin
from api.routes.tasks import (
    archived_task_summary_data,
    normalize_query_datetime,
    task_summary_data,
)
from contracts.auth import (
    AdminAuditEventResponse,
    AdminAuditListResponse,
    AdminPasswordResetRequest,
    AdminPasswordResetResponse,
    AdminUserListResponse,
    AdminUserSummaryResponse,
)
from contracts.task import (
    AdminTaskListResponse,
    AdminTaskSummaryResponse,
    TaskArchivedResponse,
    TaskRestoredResponse,
)
from core.settings import SETTINGS
from core.task_definitions import TaskStatus
from core.user_records import UserRecord, UserRole
from repositories.task_repository import task_repository
from repositories.task_repository_contracts import TaskNotFoundError
from services.archive_service import archive_task, restore_task
from services.audit_service import append_audit_event, list_audit_events
from services.auth_service import hash_password


router = APIRouter(prefix="/admin", tags=["管理员"])


def _require_target_user(user_id: str) -> UserRecord:
    user = get_user_repository().get_by_user_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    return user


def _verify_target_task_owner(user_id: str, task_id: str) -> None:
    try:
        owner_user_id = task_repository.get_task_user_id(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc
    if owner_user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        )


@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    role: UserRole | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    _: UserRecord = Depends(require_admin),
) -> AdminUserListResponse:
    repository = get_user_repository()
    users, total = repository.list_users_page(
        limit=limit,
        offset=offset,
        query=q,
        role=role,
        is_active=is_active,
    )
    return AdminUserListResponse(
        items=[
            AdminUserSummaryResponse(
                user_id=user.user_id,
                username=user.username,
                role=user.role,
                is_active=user.is_active,
                must_change_password=user.must_change_password,
                created_at=user.created_at,
                updated_at=user.updated_at,
            )
            for user in users
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/tasks", response_model=AdminTaskListResponse)
def list_tasks(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: TaskStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, min_length=1, max_length=100),
    owner_username: str | None = Query(default=None, min_length=3, max_length=32),
    archived: bool = Query(default=False),
    _: UserRecord = Depends(require_admin),
) -> AdminTaskListResponse:
    user_repository = get_user_repository()
    owner_id: str | None = None
    if owner_username is not None:
        owner = user_repository.get_by_username(owner_username)
        if owner is None:
            return AdminTaskListResponse(
                items=[], total=0, limit=limit, offset=offset, archived=archived
            )
        owner_id = owner.user_id

    if archived:
        records, total = task_repository.list_archived_tasks(
            limit=limit,
            offset=offset,
            status=status_filter,
            query=q,
            user_id=owner_id,
        )
    else:
        records, total = task_repository.list_tasks(
            limit=limit,
            offset=offset,
            status=status_filter,
            query=q,
            user_id=owner_id,
        )

    task_owners = task_repository.get_task_user_ids(
        [record.task_id for record in records]
    )
    users_by_id = user_repository.get_by_user_ids(
        [user_id for user_id in task_owners.values() if user_id is not None]
    )
    items: list[AdminTaskSummaryResponse] = []
    for record in records:
        summary = (
            archived_task_summary_data(record)
            if archived
            else task_summary_data(record)
        )
        owner_user_id = task_owners.get(record.task_id)
        owner = users_by_id.get(owner_user_id) if owner_user_id is not None else None
        items.append(
            AdminTaskSummaryResponse(
                **summary.model_dump(),
                owner_user_id=owner_user_id,
                owner_username=owner.username if owner is not None else None,
            )
        )

    return AdminTaskListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
        archived=archived,
    )


@router.post(
    "/users/{user_id}/reset-password",
    response_model=AdminPasswordResetResponse,
)
def reset_user_password(
    user_id: str,
    request: AdminPasswordResetRequest,
    current_admin: UserRecord = Depends(require_admin),
) -> AdminPasswordResetResponse:
    target = _require_target_user(user_id)
    repository = get_user_repository()
    updated = repository.update_password(
        target.username,
        hash_password(request.new_password),
        must_change_password=True,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在",
        )
    append_audit_event(
        operation="admin_password_reset",
        timestamp=datetime.now(timezone.utc),
        actor_user_id=current_admin.user_id,
        target_user_id=target.user_id,
        audit_dir=SETTINGS.task_archive_dir,
    )
    return AdminPasswordResetResponse(
        user_id=target.user_id,
        username=target.username,
    )


@router.delete(
    "/users/{user_id}/tasks/{task_id}",
    response_model=TaskArchivedResponse,
)
def archive_user_task(
    user_id: str,
    task_id: str,
    current_admin: UserRecord = Depends(require_admin),
) -> TaskArchivedResponse:
    _require_target_user(user_id)
    _verify_target_task_owner(user_id, task_id)

    try:
        task_data = archive_task(
            task_id,
            actor_user_id=current_admin.user_id,
            target_user_id=user_id,
            repository=task_repository,
            output_dir=SETTINGS.output_dir,
            archive_dir=SETTINGS.task_archive_dir,
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


@router.post(
    "/users/{user_id}/tasks/{task_id}/restore",
    response_model=TaskRestoredResponse,
)
def restore_user_task(
    user_id: str,
    task_id: str,
    current_admin: UserRecord = Depends(require_admin),
) -> TaskRestoredResponse:
    _require_target_user(user_id)
    _verify_target_task_owner(user_id, task_id)
    try:
        task_data = restore_task(
            task_id,
            actor_user_id=current_admin.user_id,
            target_user_id=user_id,
            repository=task_repository,
            output_dir=SETTINGS.output_dir,
            archive_dir=SETTINGS.task_archive_dir,
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


@router.get("/audit", response_model=AdminAuditListResponse)
def query_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    operation: str | None = Query(default=None, min_length=1, max_length=64),
    actor_user_id: str | None = Query(default=None, min_length=1, max_length=64),
    target_user_id: str | None = Query(default=None, min_length=1, max_length=64),
    task_id: str | None = Query(default=None, min_length=1, max_length=128),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    _: UserRecord = Depends(require_admin),
) -> AdminAuditListResponse:
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
    events, total, invalid_lines = list_audit_events(
        audit_dir=SETTINGS.task_archive_dir,
        limit=limit,
        offset=offset,
        operation=operation,
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        task_id=task_id,
        created_from=normalized_from,
        created_to=normalized_to,
    )
    return AdminAuditListResponse(
        items=[AdminAuditEventResponse(**event) for event in events],
        total=total,
        limit=limit,
        offset=offset,
        invalid_lines=invalid_lines,
    )
