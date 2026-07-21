'''由 RQ worker 执行的模型推理作业'''

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from rq import get_current_job

from core.settings import SETTINGS
from core.task_definitions import JobStatus
from services.task_runner import run_task_models
from services.task_files import get_task_dir
from services.task_state import update_task_execution_status

logger = logging.getLogger(__name__)


def run_task_job(task_id: str, threshold: float) -> dict[str, Any]:
    '''顺序执行一个任务的分类和分割推理'''
    job = get_current_job()
    if job is None:
        raise RuntimeError("推理作业必须由 RQ worker 执行")

    task_dir = get_task_dir(SETTINGS.output_dir, task_id)
    status_kwargs: dict[str, Any] = {
        "job_id": job.id,
        "queue_name": SETTINGS.task_queue_name,
    }
    attempt = _get_job_attempt(job)
    if attempt is not None:
        status_kwargs["attempt"] = attempt
    update_task_execution_status(
        task_dir,
        JobStatus.RUNNING,
        **status_kwargs,
    )
    started_at = perf_counter()

    try:
        run_result = run_task_models(task_dir, threshold)
    except Exception as exc:
        execution_ms = round((perf_counter() - started_at) * 1000, 3)
        retry_pending = bool(getattr(job, "should_retry", lambda: False)())
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
    return {
        "task_id": task_id,
        "status": task_record.status.value,
        "completed_models": [model.value for model in task_record.completed_models],
        "classification_result_file": run_result.classification_result[
            "model_result_path"
        ],
        "segmentation_result_file": run_result.segmentation_result[
            "model_result_path"
        ],
    }


def _get_job_attempt(job: Any) -> int | None:
    '''根据 RQ 剩余重试次数计算当前执行次数'''
    retries_left = getattr(job, "retries_left", None)
    if not isinstance(retries_left, int):
        return None
    return SETTINGS.task_job_max_retries - retries_left + 1
