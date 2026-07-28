'''默认任务仓储实例'''

from __future__ import annotations

from core.settings import SETTINGS
from repositories.sqlite_task_repository import SqliteTaskRepository
from repositories.task_repository_contracts import TaskRepository


task_repository: TaskRepository = SqliteTaskRepository(SETTINGS.task_database_path)
