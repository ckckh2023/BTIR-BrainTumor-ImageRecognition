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
) -> None:
    '''记录安全审计事件'''
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
        file_descriptor = os.open(audit_dir / "audit.jsonl", flags, 0o600)
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
    audit_path = audit_dir / "audit.jsonl"
    if not audit_path.is_file():
        return [], 0, 0

    normalized_from = _normalize_timestamp(created_from) if created_from else None
    normalized_to = _normalize_timestamp(created_to) if created_to else None
    page_size = offset + limit
    selected: list[tuple[datetime, int, dict[str, object]]] = []
    matching_count = 0
    invalid_lines = 0
    with audit_path.open(encoding="utf-8") as audit_file:
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
            elif entry[:2] > selected[0][:2]:
                heapq.heapreplace(selected, entry)

    selected.sort(key=lambda item: (item[0], item[1]), reverse=True)
    page = [event for _, _, event in selected[offset:]]
    return page, matching_count, invalid_lines
