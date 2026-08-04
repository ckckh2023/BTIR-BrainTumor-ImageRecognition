'''安全敏感操作的结构化审计记录'''

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import heapq
import json
import os
from pathlib import Path
from threading import Lock
from typing import Iterator

from core.settings import SETTINGS


_AUDIT_THREAD_LOCK = Lock()
_AUDIT_LOG_FILENAME = "audit.jsonl"
_ROTATED_AUDIT_LOG_GLOB = "audit.*.jsonl"


@contextmanager
def _audit_file_lock(lock_path: Path) -> Iterator[None]:
    '''使用独立锁文件串行化同一主机上的多进程审计写入'''
    lock_descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(lock_descriptor).st_size == 0:
                os.write(lock_descriptor, b"\0")
            os.lseek(lock_descriptor, 0, os.SEEK_SET)
            msvcrt.locking(lock_descriptor, msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                os.lseek(lock_descriptor, 0, os.SEEK_SET)
                msvcrt.locking(lock_descriptor, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_descriptor, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
    finally:
        os.close(lock_descriptor)


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rotated_audit_log_paths(audit_dir: Path) -> list[Path]:
    paths: list[tuple[int, str, Path]] = []
    for path in audit_dir.glob(_ROTATED_AUDIT_LOG_GLOB):
        try:
            if path.is_file():
                paths.append((path.stat().st_mtime_ns, path.name, path))
        except OSError:
            continue
    return [path for _, _, path in sorted(paths)]


def _prune_rotated_audit_logs(
    audit_dir: Path,
    *,
    retention_days: int,
    max_rotated_files: int,
) -> None:
    '''清理超过保留期或份数上限的审计日志分片'''
    paths = _rotated_audit_log_paths(audit_dir)
    cutoff_timestamp = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    retained_paths: list[Path] = []
    for path in paths:
        if path.stat().st_mtime < cutoff_timestamp:
            path.unlink(missing_ok=True)
        else:
            retained_paths.append(path)

    overflow = len(retained_paths) - max_rotated_files
    for path in retained_paths[: max(overflow, 0)]:
        path.unlink(missing_ok=True)


def _rotate_audit_log(audit_dir: Path) -> None:
    audit_path = audit_dir / _AUDIT_LOG_FILENAME
    if not audit_path.is_file() or audit_path.stat().st_size == 0:
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    candidate = audit_dir / f"audit.{timestamp}.jsonl"
    sequence = 1
    while candidate.exists():
        candidate = audit_dir / f"audit.{timestamp}.{sequence}.jsonl"
        sequence += 1
    audit_path.replace(candidate)


def _audit_log_paths(audit_dir: Path) -> list[Path]:
    paths = _rotated_audit_log_paths(audit_dir)
    audit_path = audit_dir / _AUDIT_LOG_FILENAME
    if audit_path.is_file():
        paths.append(audit_path)
    return paths


def append_audit_event(
    *,
    operation: str,
    timestamp: datetime,
    actor_user_id: str | None = None,
    target_user_id: str | None = None,
    task_id: str | None = None,
    outcome: str | None = None,
    source_ip: str | None = None,
    audit_dir: Path = SETTINGS.task_archive_dir,
    max_bytes: int | None = None,
    retention_days: int | None = None,
    max_rotated_files: int | None = None,
) -> None:
    '''记录安全审计事件'''
    max_bytes = SETTINGS.audit_log_max_bytes if max_bytes is None else max_bytes
    retention_days = (
        SETTINGS.audit_log_retention_days
        if retention_days is None
        else retention_days
    )
    max_rotated_files = (
        SETTINGS.audit_log_max_rotated_files
        if max_rotated_files is None
        else max_rotated_files
    )
    if max_bytes <= 0 or retention_days < 0 or max_rotated_files < 0:
        raise ValueError("审计日志轮转配置无效")
    audit_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "operation": operation,
        "timestamp": timestamp.isoformat(),
    }
    if actor_user_id is not None:
        entry["actor_user_id"] = actor_user_id
    if target_user_id is not None:
        entry["target_user_id"] = target_user_id
    if task_id is not None:
        entry["task_id"] = task_id
    if outcome is not None:
        entry["outcome"] = outcome
    if source_ip is not None:
        entry["source_ip"] = source_ip
    encoded_entry = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    with _AUDIT_THREAD_LOCK, _audit_file_lock(audit_dir / "audit.lock"):
        _prune_rotated_audit_logs(
            audit_dir,
            retention_days=retention_days,
            max_rotated_files=max_rotated_files,
        )
        audit_path = audit_dir / _AUDIT_LOG_FILENAME
        if (
            audit_path.is_file()
            and audit_path.stat().st_size + len(encoded_entry) > max_bytes
        ):
            _rotate_audit_log(audit_dir)
            _prune_rotated_audit_logs(
                audit_dir,
                retention_days=retention_days,
                max_rotated_files=max_rotated_files,
            )

        file_descriptor = os.open(audit_path, flags, 0o600)
        try:
            remaining = memoryview(encoded_entry)
            while remaining:
                written = os.write(file_descriptor, remaining)
                if written <= 0:
                    raise OSError("审计日志未完整写入")
                remaining = remaining[written:]
        finally:
            os.close(file_descriptor)


def list_audit_events(
    *,
    audit_dir: Path = SETTINGS.task_archive_dir,
    limit: int,
    offset: int,
    operation: str | None = None,
    actor_user_id: str | None = None,
    target_user_id: str | None = None,
    task_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> tuple[list[dict[str, object]], int, int]:
    '''读取并筛选审计日志'''
    audit_paths = _audit_log_paths(audit_dir)
    if not audit_paths:
        return [], 0, 0

    normalized_from = _normalize_timestamp(created_from) if created_from else None
    normalized_to = _normalize_timestamp(created_to) if created_to else None
    page_size = offset + limit
    selected: list[tuple[datetime, int, int, dict[str, object]]] = []
    matching_count = 0
    invalid_lines = 0
    for file_index, audit_path in enumerate(audit_paths):
        try:
            audit_file = audit_path.open(encoding="utf-8")
        except OSError:
            continue
        with audit_file:
            for line_number, raw_line in enumerate(audit_file, 1):
                try:
                    raw_event = json.loads(raw_line)
                    event_operation = raw_event["operation"]
                    timestamp = _normalize_timestamp(
                        datetime.fromisoformat(raw_event["timestamp"])
                    )
                    if not isinstance(event_operation, str):
                        raise ValueError
                    optional_fields = {
                        field: raw_event.get(field)
                        for field in (
                            "actor_user_id",
                            "target_user_id",
                            "task_id",
                            "outcome",
                            "source_ip",
                        )
                    }
                    if any(
                        value is not None and not isinstance(value, str)
                        for value in optional_fields.values()
                    ):
                        raise ValueError
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    invalid_lines += 1
                    continue

                if operation is not None and event_operation != operation:
                    continue
                if actor_user_id is not None and optional_fields["actor_user_id"] != actor_user_id:
                    continue
                if target_user_id is not None and optional_fields["target_user_id"] != target_user_id:
                    continue
                if task_id is not None and optional_fields["task_id"] != task_id:
                    continue
                if normalized_from is not None and timestamp < normalized_from:
                    continue
                if normalized_to is not None and timestamp > normalized_to:
                    continue

                matching_count += 1
                entry = (
                    timestamp,
                    file_index,
                    line_number,
                    {
                        "operation": event_operation,
                        "timestamp": timestamp,
                        **optional_fields,
                    },
                )
                if page_size <= 0:
                    continue
                if len(selected) < page_size:
                    heapq.heappush(selected, entry)
                elif entry[:3] > selected[0][:3]:
                    heapq.heapreplace(selected, entry)

    selected.sort(key=lambda item: item[:3], reverse=True)
    page = [event for _, _, _, event in selected[offset:]]
    return page, matching_count, invalid_lines
