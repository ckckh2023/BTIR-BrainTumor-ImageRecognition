'''由 RQ worker 执行的模型推理作业'''

from __future__ import annotations

import logging
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any, Callable

from rq import get_current_job

from core.settings import SETTINGS
from core.task_definitions import JobStatus, TaskStatus
from repositories.task_repository import task_repository
from services.task_runner import TaskCancellationRequested, run_task_models
from services.task_files import get_task_dir
from services.task_state import update_task_execution_status

logger = logging.getLogger(__name__)


def run_task_job(task_id: str) -> dict[str, Any]:
    '''顺序执行一个任务的分类和分割推理'''
    job = get_current_job()
    if job is None:
        raise RuntimeError("推理作业必须由 RQ worker 执行")

    task_dir = get_task_dir(SETTINGS.output_dir, task_id)
    should_cancel = _build_cancellation_checker(job, task_dir)
    status_kwargs: dict[str, Any] = {
        "job_id": job.id,
        "queue_name": _get_job_queue_name(job),
    }
    attempt = _get_job_attempt(job)
    if attempt is not None:
        status_kwargs["attempt"] = attempt
    if should_cancel():
        return _finish_canceled_task(task_dir, job, attempt, execution_ms=0.0)
    update_task_execution_status(
        task_dir,
        JobStatus.RUNNING,
        **status_kwargs,
    )
    started_at = perf_counter()

    try:
        run_result = run_task_models(
            task_dir,
            should_cancel=should_cancel,
            progress_callback=lambda stage, percentage: _record_job_progress(
                job,
                task_id,
                stage,
                percentage,
            ),
        )
    except TaskCancellationRequested:
        execution_ms = round((perf_counter() - started_at) * 1000, 3)
        return _finish_canceled_task(task_dir, job, attempt, execution_ms=execution_ms)
    except Exception as exc:
        execution_ms = round((perf_counter() - started_at) * 1000, 3)
        retry_attr = getattr(job, "should_retry", False)
        retry_pending = bool(retry_attr() if callable(retry_attr) else retry_attr)
        update_task_execution_status(
            task_dir,
            JobStatus.QUEUED if retry_pending else JobStatus.FAILED,
            job_id=job.id,
            error=None if retry_pending else "模型推理失败，请稍后重试或联系管理员",
            error_code="inference_failed",
            error_detail=None if retry_pending else f"{type(exc).__name__}: {exc}",
            execution_ms=execution_ms,
        )
        logger.error(
            "task inference failed task_id=%s job_id=%s attempt=%s execution_ms=%s retry_pending=%s",
            task_id, job.id, attempt, execution_ms, retry_pending,
        )
        raise

    execution_ms = round((perf_counter() - started_at) * 1000, 3)
    task_record = update_task_execution_status(
        task_dir,
        JobStatus.SUCCEEDED,
        job_id=job.id,
        execution_ms=execution_ms,
    )
    logger.info(
        "task inference succeeded task_id=%s job_id=%s attempt=%s execution_ms=%s model_inference_ms=%s",
        task_id,
        job.id,
        attempt,
        execution_ms,
        getattr(run_result, "total_inference_ms", None),
    )
    result_payload = {
        "task_id": task_id,
        "status": task_record.status.value,
        "completed_models": [model.value for model in task_record.completed_models],
        "segmentation_result_file": run_result.segmentation_result[
            "model_result_path"
        ],
    }
    result_payload["classification_result_file"] = (
        run_result.classification_result["model_result_path"]
    )
    supplementary_analysis = getattr(run_result, "supplementary_analysis", {})
    result_payload["supplementary_analysis_status"] = supplementary_analysis.get(
        "status",
        "disabled",
    )
    return result_payload


def _get_job_attempt(job: Any) -> int | None:
    '''根据 RQ 剩余重试次数计算当前执行次数'''
    retries_left = getattr(job, "retries_left", None)
    if not isinstance(retries_left, int):
        return None
    return SETTINGS.task_job_max_retries - retries_left + 1


def _is_cancellation_requested(job: Any, task_dir: Path | None = None) -> bool:
    '''同时读取 RQ 标记与任务状态，避免进度元数据并发写入丢失取消信号'''
    refresh = getattr(job, "refresh", None)
    if callable(refresh):
        refresh()
    metadata = getattr(job, "meta", None)
    if metadata is None:
        return False
    if bool(metadata.get("cancel_requested")):
        return True
    if task_dir is None:
        return False
    return task_repository.load(task_dir).status in {
        TaskStatus.CANCEL_REQUESTED,
        TaskStatus.CANCELED,
    }


def _build_cancellation_checker(job: Any, task_dir: Path) -> Callable[[], bool]:
    '''按短间隔刷新取消状态，避免滑窗推理重复访问 Redis 和 SQLite'''

    last_checked_at: float | None = None
    cancellation_requested = False

    def should_cancel() -> bool:
        nonlocal last_checked_at, cancellation_requested
        now = monotonic()
        if cancellation_requested:
            return True
        if (
            last_checked_at is not None
            and now - last_checked_at < SETTINGS.task_cancel_check_interval_seconds
        ):
            return False
        last_checked_at = now
        cancellation_requested = _is_cancellation_requested(job, task_dir)
        return cancellation_requested

    return should_cancel


def _record_job_progress(
    job: Any,
    task_id: str,
    stage: str,
    percentage: int,
) -> None:
    '''将真实阶段写入 worker 日志；RQ 可用时同步保存到作业元数据'''
    metadata = getattr(job, "meta", None)
    if (
        isinstance(metadata, dict)
        and metadata.get("progress") == percentage
        and metadata.get("progress_stage") == stage
    ):
        return
    refresh = getattr(job, "refresh", None)
    if callable(refresh):
        refresh()
    metadata = getattr(job, "meta", None)
    if isinstance(metadata, dict):
        metadata["progress"] = percentage
        metadata["progress_stage"] = stage
        save_meta = getattr(job, "save_meta", None)
        if callable(save_meta):
            save_meta()
    logger.info(
        "task inference progress task_id=%s job_id=%s progress=%s stage=%s",
        task_id,
        job.id,
        percentage,
        stage,
    )


def _finish_canceled_task(
    task_dir,
    job: Any,
    attempt: int | None,
    *,
    execution_ms: float,
) -> dict[str, Any]:
    task_record = update_task_execution_status(
        task_dir,
        JobStatus.CANCELED,
        job_id=job.id,
        queue_name=_get_job_queue_name(job),
        attempt=attempt,
        execution_ms=execution_ms,
    )
    logger.info(
        "task inference canceled task_id=%s job_id=%s attempt=%s execution_ms=%s",
        task_dir.name,
        job.id,
        attempt,
        execution_ms,
    )
    return {
        "task_id": task_dir.name,
        "status": task_record.status.value,
        "completed_models": [model.value for model in task_record.completed_models],
    }


def _get_job_queue_name(job: Any) -> str:
    '''使用 RQ 作业实际来源队列，测试替身则回退到项目推理队列'''

    origin = getattr(job, "origin", None)
    if isinstance(origin, str) and origin.strip():
        return origin
    return SETTINGS.task_queue_name
