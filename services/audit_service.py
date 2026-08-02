'''安全敏感操作的结构化审计记录'''

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from core.settings import SETTINGS


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
    audit_dir: Path = SETTINGS.task_archive_dir,
) -> None:
    '''记录操作者、目标用户和任务，不记录密码等敏感内容。'''
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
    with (audit_dir / "audit.jsonl").open("a", encoding="utf-8") as audit_file:
        audit_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
    '''读取并筛选审计日志；损坏行会被跳过并单独计数。'''
    audit_path = audit_dir / "audit.jsonl"
    if not audit_path.is_file():
        return [], 0, 0

    normalized_from = _normalize_timestamp(created_from) if created_from else None
    normalized_to = _normalize_timestamp(created_to) if created_to else None
    matching: list[tuple[datetime, int, dict[str, object]]] = []
    invalid_lines = 0
    for line_number, raw_line in enumerate(
        audit_path.read_text(encoding="utf-8").splitlines(),
        1,
    ):
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
                for field in ("actor_user_id", "target_user_id", "task_id")
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
        matching.append(
            (
                timestamp,
                line_number,
                {
                    "operation": event_operation,
                    "timestamp": timestamp,
                    **optional_fields,
                },
            )
        )

    matching.sort(key=lambda item: (item[0], item[1]), reverse=True)
    page = [event for _, _, event in matching[offset : offset + limit]]
    return page, len(matching), invalid_lines
