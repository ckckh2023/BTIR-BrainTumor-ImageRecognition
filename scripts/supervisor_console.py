'''仅使用标准库，将守护事件和推理日志显示为简洁的终端状态。'''

from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import signal
import sys
import time
from typing import TextIO
import unicodedata


class Console:
    def __init__(self, stream: TextIO = sys.stdout) -> None:
        self.stream = stream
        self.interactive = stream.isatty() and os.getenv("TERM") != "dumb"
        self.status = ""
        self.started_at = time.monotonic()
        self.frame = 0
        self.warning_at = float("-inf")
        self.task_active = False

    def clear(self) -> None:
        if self.interactive:
            self.stream.write("\r\033[2K")

    def emit(self, message: str) -> None:
        self.clear()
        print(f"[BTIR] {message}", file=self.stream, flush=True)

    def set_status(self, message: str) -> None:
        if message == self.status:
            return
        self.status = message
        self.started_at = time.monotonic()
        if not self.interactive:
            self.emit(message)

    def draw(self) -> None:
        if not self.interactive or not self.status:
            return
        frames = ("-", "\\", "|", "/")
        elapsed = int(time.monotonic() - self.started_at)
        self.clear()
        text = f"{frames[self.frame % 4]} {self.status}（{elapsed} 秒）"
        available = max(1, shutil.get_terminal_size().columns - 1)
        visible = ""
        width = 0
        for character in text:
            width += 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1
            if width >= available:
                visible += "…"
                break
            visible += character
        self.stream.write(visible)
        self.stream.flush()
        self.frame += 1

    def supervisor_event(self, line: str) -> None:
        message = line.partition("[守护进程] ")[2]
        if message.startswith("[状态] "):
            status = message.removeprefix("[状态] ")
            if self.task_active and status == "运行中":
                return
            if status.startswith("正在启动 3D"):
                self.task_active = False
            self.set_status(status)
        elif message:
            self.emit(message)

    def worker_event(self, line: str) -> None:
        progress = re.search(r"任务推理进度 任务=(\S+) 作业=\S+ 进度=(\d+)% 阶段=(.+)", line)
        if progress:
            self.task_active = True
            task_id, percentage, stage = progress.groups()
            self.set_status(f"任务 {task_id} · {percentage}% · {stage}")
            return
        outcome = re.search(r"(任务推理完成|任务推理失败|任务推理已取消) 任务=(\S+)", line)
        if outcome:
            self.task_active = False
            message, task_id = outcome.groups()
            suffix = "，等待自动重试" if "等待重试=True" in line else ""
            self.emit(f"{message}：{task_id}{suffix}")
            self.set_status("运行中")
        elif any(marker in line for marker in ("ERROR", "WARNING", "Traceback", "预加载失败")):
            now = time.monotonic()
            if now - self.warning_at >= 5:
                self.emit("推理进程异常（日志：worker.stdout.log、worker.stderr.log）")
                self.warning_at = now


class LogReader:
    def __init__(self, path: Path, offset: int = 0) -> None:
        self.path = path
        self.offset = offset
        self.pending = b""

    def lines(self) -> list[str]:
        try:
            with self.path.open("rb") as source:
                if source.seek(0, 2) < self.offset:
                    self.offset = 0
                    self.pending = b""
                source.seek(self.offset)
                data = source.read(256 * 1024)
                self.offset = source.tell()
        except FileNotFoundError:
            return []
        parts = (self.pending + data).split(b"\n")
        self.pending = parts.pop()[-16384:]
        return [line.decode("utf-8", errors="replace").rstrip("\r") for line in parts]


def main() -> None:
    parser = argparse.ArgumentParser(description="显示 BTIR 守护进程的实时状态")
    parser.add_argument("events", type=Path)
    parser.add_argument("log_directory", type=Path)
    parser.add_argument("parent_pid", type=int)
    parser.add_argument("stdout_offset", type=int)
    parser.add_argument("stderr_offset", type=int)
    args = parser.parse_args()
    console = Console()
    events = LogReader(args.events)
    workers = [
        LogReader(args.log_directory / "worker.stdout.log", args.stdout_offset),
        LogReader(args.log_directory / "worker.stderr.log", args.stderr_offset),
    ]
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    # Ctrl+C 由守护脚本统一处理，保留退出期间的状态展示。
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    Path(f"{args.events}.ready").touch()
    try:
        while True:
            # 先处理任务日志，确保最终退出事件显示在最后。
            for reader in workers:
                for line in reader.lines():
                    console.worker_event(line)
            for line in events.lines():
                console.supervisor_event(line)
            if stopping or os.getppid() != args.parent_pid:
                break
            console.draw()
            time.sleep(0.12)
    finally:
        console.clear()
        console.stream.flush()


if __name__ == "__main__":
    main()
