'''终端状态与阶段进度输出'''

from __future__ import annotations

import os
import sys
from typing import TextIO


_COLORS = {
    "info": "\033[36m",
    "success": "\033[32m",
    "error": "\033[31m",
    "reset": "\033[0m",
}


def print_event(
    message: str,
    *,
    level: str = "info",
    stream: TextIO | None = None,
) -> None:
    '''输出适配交互终端的彩色状态信息'''
    stream = stream or sys.stdout
    prefix = {"info": ">", "success": "OK", "error": "ERR"}.get(level, "-")
    text = f"[BTIR] {prefix} {message}"
    if _supports_color(stream):
        text = f"{_COLORS.get(level, '')}{text}{_COLORS['reset']}"
    print(text, file=stream, flush=True)


class ConsoleProgress:
    '''按真实推理阶段渲染 0%、50%、100% 进度'''

    def __init__(self, stream: TextIO | None = None, *, width: int = 20) -> None:
        self.stream = stream or sys.stdout
        self.width = width
        self._interactive = bool(getattr(self.stream, "isatty", lambda: False)())

    def update(self, stage: str, percentage: int) -> None:
        percentage = max(0, min(100, percentage))
        filled = round(self.width * percentage / 100)
        bar = f"{'#' * filled}{'-' * (self.width - filled)}"
        text = f"[BTIR] [{bar}] {percentage:>3}% {stage}"
        if _supports_color(self.stream):
            text = f"{_COLORS['info']}{text}{_COLORS['reset']}"

        if self._interactive:
            end = "\n" if percentage == 100 else "\r"
            print(text, file=self.stream, end=end, flush=True)
            return
        print(text, file=self.stream, flush=True)


def _supports_color(stream: TextIO) -> bool:
    return (
        not os.getenv("NO_COLOR")
        and os.getenv("TERM") != "dumb"
        and bool(getattr(stream, "isatty", lambda: False)())
    )
