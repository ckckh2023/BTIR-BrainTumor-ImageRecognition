'''任务归档与归档区永久删除；与全量 clear 清理隔离'''

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
from typing import Literal

from core.settings import SETTINGS
from core.task_definitions import TaskStatus
from core.task_records import TaskRecord
from repositories.task_repository import TaskRepository, task_repository
from services.task_lock import task_write_lock


ArchiveOperation = Literal["archive", "purge"]


@dataclass(frozen=True)
class ArchiveReport:
    '''一次归档或永久删除预览/执行的汇总'''

    operation: ArchiveOperation
    dry_run: bool
    processed_task_ids: list[str] = field(default_factory=list)
    skipped_task_ids: list[str] = field(default_factory=list)


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
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            current.archived_at = now
            try:
                repository.save(source, current)
            except Exception:
                shutil.move(str(destination), str(source))
                raise
            _append_audit(
                archive_dir,
                operation="archive",
                task_id=current.task_id,
                timestamp=now,
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
    if record.status in {TaskStatus.SUCCEEDED, TaskStatus.COMPLETED}:
        retention_days = SETTINGS.succeeded_task_retention_days
    elif record.status is TaskStatus.FAILED:
        retention_days = SETTINGS.failed_task_retention_days
    else:
        return False
    return record.updated_at <= now - timedelta(days=retention_days)


def _is_purge_eligible(record: TaskRecord, now: datetime) -> bool:
    return (
        record.archived_at is not None
        and record.archived_at <= now - timedelta(days=SETTINGS.task_archive_grace_days)
    )


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
