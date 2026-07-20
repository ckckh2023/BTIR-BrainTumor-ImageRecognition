'''任务执行状态与运行记录的管理'''

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.task_definitions import JobStatus, ModelName, TaskStatus
from repositories.task_repository import task_repository
from services.task_files import task_relative_path
from services.task_lock import task_write_lock


ASYNC_TASK_STATUSES = frozenset(JobStatus)


def mark_task_completed(task_dir: Path, *models: ModelName | str) -> None:
    '''将指定模型标记为已完成，并更新任务元数据'''
    if not task_repository.exists(task_dir):
        return

    record = task_repository.load(task_dir)
    completed = set(record.get("completed_models", []))
    completed.update(ModelName(model).value for model in models)
    record["completed_models"] = sorted(completed)
    if record.get("status") not in {
        TaskStatus.QUEUED.value,
        TaskStatus.RUNNING.value,
    }:
        record["status"] = (
            TaskStatus.COMPLETED.value
            if {ModelName.CLASSIFICATION.value, ModelName.SEGMENTATION.value}
            <= completed
            else TaskStatus.PARTIAL.value
        )
    record["updated_at"] = datetime.now().astimezone().isoformat()
    task_repository.save(task_dir, record)


def update_task_execution_status(
    task_dir: Path,
    status: JobStatus | str,
    *,
    job_id: str,
    queue_name: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    '''更新 RQ 作业状态，并同步写入任务元数据'''
    try:
        job_status = JobStatus(status)
    except ValueError as exc:
        raise ValueError(f"不支持的异步任务状态：{status}") from exc

    with task_write_lock(task_dir.name):
        record = task_repository.load(task_dir)
        job = dict(record.get("job") or {})
        existing_job_id = job.get("id")
        if existing_job_id and existing_job_id != job_id:
            raise ValueError("任务正在由另一异步作业处理")

        now = datetime.now().astimezone().isoformat()
        job["id"] = job_id
        job["status"] = job_status.value
        if queue_name:
            job["queue"] = queue_name
        if job_status is JobStatus.QUEUED:
            job["queued_at"] = now
        elif job_status is JobStatus.RUNNING:
            job["started_at"] = now
        else:
            job["finished_at"] = now

        record["status"] = job_status.value
        record["job"] = job
        record["updated_at"] = now
        if error:
            record["error"] = {"message": error, "updated_at": now}
        elif job_status is not JobStatus.FAILED:
            record.pop("error", None)
        task_repository.save(task_dir, record)
        return record


def record_task_run(
    task_dir: Path,
    model_name: ModelName | str,
    result_path: Path,
) -> None:
    '''记录一条模型运行历史到任务元数据中'''
    if not task_repository.exists(task_dir):
        return

    record = task_repository.load(task_dir)
    record.setdefault("runs", []).append(
        {
            "run_id": result_path.parent.name,
            "model": ModelName(model_name).value,
            "result_file": task_relative_path(task_dir, result_path),
            "created_at": datetime.now().astimezone().isoformat(),
        }
    )
    record["updated_at"] = datetime.now().astimezone().isoformat()
    task_repository.save(task_dir, record)
