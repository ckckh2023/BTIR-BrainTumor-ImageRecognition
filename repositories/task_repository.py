'''任务元数据的数据访问接口及 JSON 实现'''

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol


class TaskRepository(Protocol):
    '''任务元数据存储需要提供的最小接口'''

    def exists(self, task_dir: Path) -> bool:
        '''返回任务元数据是否存在'''

    def load(self, task_dir: Path) -> dict[str, Any]:
        '''读取一条任务元数据'''

    def save(self, task_dir: Path, record: dict[str, Any]) -> Path:
        '''保存一条任务元数据'''


class JsonTaskRepository:
    '''以任务目录中的 task.json 保存任务元数据'''

    filename = "task.json"

    def _path(self, task_dir: Path) -> Path:
        return task_dir / self.filename

    def exists(self, task_dir: Path) -> bool:
        return self._path(task_dir).is_file()

    def load(self, task_dir: Path) -> dict[str, Any]:
        path = self._path(task_dir)
        if not path.is_file():
            raise ValueError("任务元数据缺失")

        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("任务元数据格式无效") from exc

        if not isinstance(record, dict):
            raise ValueError("任务元数据格式无效")
        return record

    def save(self, task_dir: Path, record: dict[str, Any]) -> Path:
        path = self._path(task_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        temporary_path = Path(temporary_name)

        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
                json.dump(record, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        except Exception:
            temporary_path.unlink(missing_ok=True)
            raise
        return path.resolve()


# 接入 SQLite 时替换
task_repository: TaskRepository = JsonTaskRepository()
