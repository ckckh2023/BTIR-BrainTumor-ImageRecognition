'''任务仓储契约与公共异常'''

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from core.task_definitions import TaskStatus
from core.task_records import TaskRecord


class TaskNotFoundError(LookupError):
    '''任务元数据不存在'''


class TaskRepositoryUnavailableError(RuntimeError):
    '''任务元数据存储不可用'''


class TaskRepository(Protocol):
    '''任务元数据存储的最小契约'''

    def exists(self, task_dir: Path) -> bool:
        '''返回任务元数据是否存在'''

    def load(self, task_dir: Path) -> TaskRecord:
        '''读取一条任务元数据'''

    def save(self, task_dir: Path, record: TaskRecord) -> Path:
        '''保存一条任务元数据'''

    def count(self) -> int:
        '''返回当前存储中的任务数量'''

    def list_tasks(
        self,
        *,
        limit: int,
        offset: int,
        status: TaskStatus | None = None,
        query: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> tuple[list[TaskRecord], int]:
        '''按创建时间倒序返回任务页和筛选后的总数'''

    def list_active_tasks(self, *, limit: int) -> list[TaskRecord]:
        '''返回仍需与 RQ 对账的活动任务'''

    def list_archive_candidates(
        self,
        *,
        succeeded_before: datetime,
        failed_before: datetime,
        limit: int,
    ) -> list[TaskRecord]:
        '''返回满足保留期的终态任务'''

    def list_purge_candidates(
        self,
        *,
        archived_before: datetime,
        limit: int,
    ) -> list[TaskRecord]:
        '''返回超过归档宽限期的任务'''

    def delete(self, task_id: str) -> None:
        '''删除一条任务元数据'''

    def delete_all(self) -> int:
        '''删除全部任务元数据，并返回删除数量'''

    def health_check(self) -> None:
        '''检查任务元数据存储是否可用'''
