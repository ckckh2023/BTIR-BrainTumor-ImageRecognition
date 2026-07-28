'''任务归档与归档区永久删除；与全量 clear 清理隔离'''

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
from typing import Literal

from core.settings import SETTINGS
from core.task_definitions import ACTIVE_ASYNC_TASK_STATUSES, TaskStatus
from core.task_records import TaskRecord
from repositories.task_repository import task_repository
from repositories.task_repository_contracts import TaskNotFoundError, TaskRepository
from services.task_lock import task_write_lock


ArchiveOperation = Literal["archive", "purge"]


@dataclass(frozen=True)
class ArchiveReport:
    '''一次归档或永久删除预览/执行的汇总'''

    operation: ArchiveOperation
    dry_run: bool
    processed_task_ids: list[str] = field(default_factory=list)
    skipped_task_ids: list[str] = field(default_factory=list)


def archive_task(
    task_id: str,
    *,
    now: datetime | None = None,
    repository: TaskRepository = task_repository,
    output_dir: Path = SETTINGS.output_dir,
    archive_dir: Path = SETTINGS.task_archive_dir,
) -> TaskRecord:
    '''立即软删除指定的非活动任务，并保留至归档宽限期结束'''
    now = now or datetime.now().astimezone()
    try:
        source = _task_directory(output_dir, task_id)
        destination = _task_directory(archive_dir / "tasks", task_id)
    except ValueError as exc:
        raise TaskNotFoundError("任务不存在") from exc

    current = repository.load(source)
    if current.archived_at is not None:
        if destination.is_dir():
            return current
        raise TaskNotFoundError("归档任务数据不存在")
    if not source.is_dir():
        raise TaskNotFoundError("任务不存在")
    if destination.exists():
        raise ValueError("任务归档目标已存在")
    _ensure_same_volume(source, destination)

    with task_write_lock(task_id):
        current = repository.load(source)
        if current.archived_at is not None:
            if destination.is_dir():
                return current
            raise TaskNotFoundError("归档任务数据不存在")
        if current.status in ACTIVE_ASYNC_TASK_STATUSES:
            raise ValueError("排队、运行或等待取消的任务不能删除")
        if not source.is_dir():
            raise TaskNotFoundError("任务不存在")
        if destination.exists():
            raise ValueError("任务归档目标已存在")
        return _move_task_to_archive(
            source=source,
            destination=destination,
            record=current,
            timestamp=now,
            repository=repository,
            archive_dir=archive_dir,
            audit_operation="archive_api",
        )


def restore_task(
    task_id: str,
    *,
    now: datetime | None = None,
    repository: TaskRepository = task_repository,
    output_dir: Path = SETTINGS.output_dir,
    archive_dir: Path = SETTINGS.task_archive_dir,
) -> TaskRecord:
    '''将尚未永久清除的归档任务恢复到活动任务目录'''
    now = now or datetime.now().astimezone()
    try:
        source = _task_directory(archive_dir / "tasks", task_id)
        destination = _task_directory(output_dir, task_id)
    except ValueError as exc:
        raise TaskNotFoundError("任务不存在") from exc

    current = repository.load(destination)
    if current.archived_at is None:
        raise ValueError("任务未归档，无需恢复")
    if not source.is_dir():
        raise TaskNotFoundError("归档任务数据不存在")
    if destination.exists():
        raise ValueError("任务恢复目标已存在")
    _ensure_same_volume(source, destination)

    with task_write_lock(task_id):
        current = repository.load(destination)
        if current.archived_at is None:
            raise ValueError("任务未归档，无需恢复")
        if not source.is_dir():
            raise TaskNotFoundError("归档任务数据不存在")
        if destination.exists():
            raise ValueError("任务恢复目标已存在")
        return _move_task_from_archive(
            source=source,
            destination=destination,
            record=current,
            timestamp=now,
            repository=repository,
            archive_dir=archive_dir,
        )


def archive_expired_tasks(
    *,
    dry_run: bool,
    limit: int = 100,
    now: datetime | None = None,
    repository: TaskRepository = task_repository,
    output_dir: Path = SETTINGS.output_dir,
    archive_dir: Path = SETTINGS.task_archive_dir,
    cleanup_enabled: bool = SETTINGS.task_cleanup_enabled,
) -> ArchiveReport:
    '''将超过保留期的终态任务移动至归档区，不删除任何数据'''
    _ensure_apply_is_enabled(dry_run, cleanup_enabled)
    now = now or datetime.now().astimezone()
    candidates = repository.list_archive_candidates(
        succeeded_before=now - timedelta(days=SETTINGS.succeeded_task_retention_days),
        failed_before=now - timedelta(days=SETTINGS.failed_task_retention_days),
        limit=limit,
    )
    report = ArchiveReport(operation="archive", dry_run=dry_run)
    for candidate in candidates:
        if not _is_archive_eligible(candidate, now):
            report.skipped_task_ids.append(candidate.task_id)
            continue

        source = _task_directory(output_dir, candidate.task_id)
        destination = _task_directory(archive_dir / "tasks", candidate.task_id)
        if not source.is_dir() or destination.exists():
            report.skipped_task_ids.append(candidate.task_id)
            continue
        _ensure_same_volume(source, destination)

        if dry_run:
            report.processed_task_ids.append(candidate.task_id)
            continue

        with task_write_lock(candidate.task_id):
            current = repository.load(source)
            if not _is_archive_eligible(current, now) or not source.is_dir() or destination.exists():
                report.skipped_task_ids.append(candidate.task_id)
                continue
            _move_task_to_archive(
                source=source,
                destination=destination,
                record=current,
                timestamp=now,
                repository=repository,
                archive_dir=archive_dir,
                audit_operation="archive",
            )
            report.processed_task_ids.append(current.task_id)
    return report


def purge_expired_archives(
    *,
    dry_run: bool,
    limit: int = 100,
    now: datetime | None = None,
    repository: TaskRepository = task_repository,
    archive_dir: Path = SETTINGS.task_archive_dir,
    cleanup_enabled: bool = SETTINGS.task_cleanup_enabled,
) -> ArchiveReport:
    '''永久删除超过归档宽限期的任务；必须显式 --apply 且启用清理'''
    _ensure_apply_is_enabled(dry_run, cleanup_enabled)
    now = now or datetime.now().astimezone()
    candidates = repository.list_purge_candidates(
        archived_before=now - timedelta(days=SETTINGS.task_archive_grace_days),
        limit=limit,
    )
    report = ArchiveReport(operation="purge", dry_run=dry_run)
    for candidate in candidates:
        if not _is_purge_eligible(candidate, now):
            report.skipped_task_ids.append(candidate.task_id)
            continue

        archived_dir = _task_directory(archive_dir / "tasks", candidate.task_id)
        pending_dir = _task_directory(archive_dir / ".purge-pending", candidate.task_id)
        if not archived_dir.is_dir() or pending_dir.exists():
            report.skipped_task_ids.append(candidate.task_id)
            continue
        _ensure_same_volume(archived_dir, pending_dir)

        if dry_run:
            report.processed_task_ids.append(candidate.task_id)
            continue

        with task_write_lock(candidate.task_id):
            current = repository.load(archived_dir)
            if not _is_purge_eligible(current, now) or not archived_dir.is_dir() or pending_dir.exists():
                report.skipped_task_ids.append(candidate.task_id)
                continue
            pending_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(archived_dir), str(pending_dir))
            try:
                repository.delete(current.task_id)
            except Exception:
                shutil.move(str(pending_dir), str(archived_dir))
                raise
            try:
                shutil.rmtree(pending_dir)
            except OSError:
                _append_audit(
                    archive_dir,
                    operation="purge_pending",
                    task_id=current.task_id,
                    timestamp=now,
                )
                raise
            _append_audit(
                archive_dir,
                operation="purge",
                task_id=current.task_id,
                timestamp=now,
            )
            report.processed_task_ids.append(current.task_id)
    return report


def _is_archive_eligible(record: TaskRecord, now: datetime) -> bool:
    if record.archived_at is not None:
        return False
    if record.status is TaskStatus.SUCCEEDED:
        retention_days = SETTINGS.succeeded_task_retention_days
    elif record.status in {TaskStatus.FAILED, TaskStatus.CANCELED}:
        retention_days = SETTINGS.failed_task_retention_days
    else:
        return False
    return record.updated_at <= now - timedelta(days=retention_days)


def _is_purge_eligible(record: TaskRecord, now: datetime) -> bool:
    return (
        record.archived_at is not None
        and record.archived_at <= now - timedelta(days=SETTINGS.task_archive_grace_days)
    )


def _move_task_to_archive(
    *,
    source: Path,
    destination: Path,
    record: TaskRecord,
    timestamp: datetime,
    repository: TaskRepository,
    archive_dir: Path,
    audit_operation: str,
) -> TaskRecord:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    record.archived_at = timestamp
    try:
        repository.save(source, record)
    except Exception:
        record.archived_at = None
        shutil.move(str(destination), str(source))
        raise
    _append_audit(
        archive_dir,
        operation=audit_operation,
        task_id=record.task_id,
        timestamp=timestamp,
    )
    return record


def _move_task_from_archive(
    *,
    source: Path,
    destination: Path,
    record: TaskRecord,
    timestamp: datetime,
    repository: TaskRepository,
    archive_dir: Path,
) -> TaskRecord:
    destination.parent.mkdir(parents=True, exist_ok=True)
    original_archived_at = record.archived_at
    original_updated_at = record.updated_at
    shutil.move(str(source), str(destination))
    record.archived_at = None
    record.updated_at = timestamp
    try:
        repository.save(destination, record)
    except Exception:
        record.archived_at = original_archived_at
        record.updated_at = original_updated_at
        shutil.move(str(destination), str(source))
        raise
    _append_audit(
        archive_dir,
        operation="restore_api",
        task_id=record.task_id,
        timestamp=timestamp,
    )
    return record


def _task_directory(root: Path, task_id: str) -> Path:
    if Path(task_id).name != task_id or task_id in {".", ".."}:
        raise ValueError("任务 ID 无效")
    return root.resolve() / task_id


def _ensure_same_volume(source: Path, destination: Path) -> None:
    if source.resolve().anchor != destination.resolve().anchor:
        raise ValueError("任务归档目录必须与输出目录位于同一磁盘卷")


def _ensure_apply_is_enabled(dry_run: bool, cleanup_enabled: bool) -> None:
    if not dry_run and not cleanup_enabled:
        raise ValueError("自动清理未启用；请先设置 BTIR_TASK_CLEANUP_ENABLED=true")


def _append_audit(
    archive_dir: Path,
    *,
    operation: str,
    task_id: str,
    timestamp: datetime,
) -> None:
    archive_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "operation": operation,
        "task_id": task_id,
        "timestamp": timestamp.isoformat(),
    }
    with (archive_dir / "audit.jsonl").open("a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(entry, ensure_ascii=False) + "\n")
