'''任务执行状态与运行记录的管理'''

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from core.task_definitions import (
    JobStatus,
    ModelName,
    TaskStatus,
    task_status_for_completed_models,
    task_status_from_job_status,
)
from core.task_records import (
    TaskErrorRecord,
    TaskJobRecord,
    TaskRecord,
    TaskRunRecord,
)
from repositories.task_repository import task_repository
from repositories.task_repository_contracts import TaskRepository
from services.task_files import task_relative_path
from services.task_lock import task_write_lock


def mark_task_queued(
    task_dir: Path,
    *,
    job_id: str,
    queue_name: str,
    max_retries: int,
    record: TaskRecord | None = None,
    repository: TaskRepository = task_repository,
) -> TaskRecord:
    '''记录已成功入队的作业；调用方需持有该任务写锁以保持入队原子性'''
    record = record or repository.load(task_dir)
    now = datetime.now().astimezone()
    record.status = TaskStatus.QUEUED
    record.job = TaskJobRecord(
        id=job_id,
        queue=queue_name,
        status=JobStatus.QUEUED,
        max_retries=max_retries,
        queued_at=now,
    )
    record.updated_at = now
    record.error = None
    repository.save(task_dir, record)
    return record


def record_model_completion(
    task_dir: Path,
    model_name: ModelName | str,
    result_path: Path,
    *,
    inference_ms: float | None = None,
    record: TaskRecord | None = None,
    repository: TaskRepository = task_repository,
) -> TaskRecord:
    '''记录模型完成状态'''

    model = ModelName(model_name)
    record = record or repository.load(task_dir)
    if record.runs is None:
        record.runs = []
    now = datetime.now().astimezone()
    record.runs.append(
        TaskRunRecord(
            run_id=result_path.parent.name,
            model=model,
            result_file=task_relative_path(task_dir, result_path),
            created_at=now,
            inference_ms=inference_ms,
        )
    )
    completed = set(record.completed_models)
    completed.add(model)
    record.completed_models = sorted(completed, key=lambda model: model.value)
    if record.status not in {
        TaskStatus.QUEUED,
        TaskStatus.RUNNING,
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELED,
    }:
        record.status = task_status_for_completed_models(
            completed,
        )
    record.updated_at = now
    repository.save(task_dir, record)
    return record


def update_task_execution_status(
    task_dir: Path,
    status: JobStatus | str,
    *,
    job_id: str,
    queue_name: str | None = None,
    error: str | None = None,
    error_code: str = "task_failed",
    error_detail: str | None = None,
    attempt: int | None = None,
    execution_ms: float | None = None,
) -> TaskRecord:
    '''更新 RQ 作业状态，并同步写入任务元数据'''
    job_status = JobStatus(status)

    with task_write_lock(task_dir.name):
        record = task_repository.load(task_dir)
        job = record.job
        existing_job_id = job.id if job else None
        if existing_job_id and existing_job_id != job_id:
            raise ValueError("任务正在由另一异步作业处理")

        now = datetime.now().astimezone()
        queued_at = now if job_status is JobStatus.QUEUED else (job.queued_at if job else None)
        started_at = now if job_status is JobStatus.RUNNING else (job.started_at if job else None)
        queue_wait_ms = job.queue_wait_ms if job else None
        if job_status is JobStatus.RUNNING and queued_at is not None:
            queue_wait_ms = round((now - queued_at).total_seconds() * 1000, 3)
        job = TaskJobRecord(
            id=job_id,
            queue=queue_name or (job.queue if job else ""),
            status=job_status,
            attempt=attempt if attempt is not None else (job.attempt if job else 0),
            max_retries=job.max_retries if job else 0,
            queued_at=queued_at,
            started_at=started_at,
            finished_at=(
                now
                if job_status in {
                    JobStatus.SUCCEEDED,
                    JobStatus.FAILED,
                    JobStatus.CANCELED,
                }
                else (job.finished_at if job else None)
            ),
            queue_wait_ms=queue_wait_ms,
            execution_ms=(
                None
                if job_status is JobStatus.QUEUED
                else (execution_ms if execution_ms is not None else (job.execution_ms if job else None))
            ),
        )
        if record.status is TaskStatus.CANCELED:
            record.status = TaskStatus.CANCELED
        elif (
            job_status is JobStatus.RUNNING
            and record.status is TaskStatus.CANCEL_REQUESTED
        ):
            record.status = TaskStatus.CANCEL_REQUESTED
        else:
            record.status = task_status_from_job_status(job_status)
        record.job = job
        record.updated_at = now
        if error:
            record.error = TaskErrorRecord(
                code=error_code,
                message=error,
                detail=error_detail,
                updated_at=now,
            )
        elif job_status is not JobStatus.FAILED:
            record.error = None
        task_repository.save(task_dir, record)
        return record
