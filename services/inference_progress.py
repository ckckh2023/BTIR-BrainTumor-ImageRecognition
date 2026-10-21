'''推理进度的阶段耗时文本及真实进度的短暂过渡。'''

from __future__ import annotations

import math
from time import time
from typing import Any


def _is_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _phase_start(percentage: int) -> int:
    return 99 if percentage >= 99 else 44 if percentage >= 44 else 0


def displayed_progress(metadata: dict[str, Any], target: int, *, now: float | None = None) -> int:
    '''在同一阶段内逐步追上已确认的完成量；无过渡元数据时兼容旧 Worker。'''
    origin = metadata.get("progress_display_from")
    started_at = metadata.get("progress_display_started_at")
    duration = metadata.get("progress_display_duration")
    if not all(_is_number(value) for value in (origin, started_at, duration)):
        return target
    if not 0 < duration <= 6 or not _phase_start(target) <= origin <= target:
        return target
    fraction = max(0.0, min(1.0, ((time() if now is None else now) - started_at) / duration))
    return min(target, int(origin + (target - origin) * fraction))


def update_progress_transition(metadata: dict[str, Any], target: int, *, now: float) -> None:
    '''以真实更新间隔选择 3–6 秒追赶时间，阶段切换立即对齐边界。'''
    previous = metadata.get("progress")
    if _is_number(previous) and previous == target:
        return
    updated_at = metadata.get("progress_updated_at")
    origin = target
    interval = 3.0
    if previous is None and target == 36:
        # 旧版直接显示百分比；新端会把 <36 视作分类起点。
        origin = 0
        interval = 6.0
    elif _is_number(previous) and _phase_start(int(previous)) == _phase_start(target) and previous < target:
        origin = displayed_progress(metadata, int(previous), now=now)
        interval = max(0, now - updated_at) if _is_number(updated_at) else 3.0
    if target - origin > 2:
        metadata["progress_display_from"] = max(_phase_start(target), origin)
        metadata["progress_display_started_at"] = now
        metadata["progress_display_duration"] = min(6.0, max(3.0, interval))
    else:
        # 小幅变化立即跟随，不给本来连续的滑窗反馈增加等待。
        for key in ("progress_display_from", "progress_display_started_at", "progress_display_duration"):
            metadata.pop(key, None)
    metadata["progress_updated_at"] = now


def stage_with_elapsed(stage: str, started_at: Any, *, now: float | None = None) -> str:
    '''每次查询计算已用时；旧 Worker 缺少时间戳时保留原文本。'''
    if isinstance(started_at, bool) or not isinstance(started_at, (int, float)):
        return stage
    if not math.isfinite(started_at):
        return stage
    elapsed = max(0, int((time() if now is None else now) - started_at))
    if elapsed < 3:
        return stage
    minutes, seconds = divmod(elapsed, 60)
    duration = f"{minutes}分{seconds:02d}秒" if minutes else f"{seconds}秒"
    return f"{stage} · 本阶段已用时 {duration}"
