'''由 RQ worker 执行的模型推理作业'''

from __future__ import annotations

from typing import Any

from rq import get_current_job

from core.settings import SETTINGS
from core.task_definitions import JobStatus
from services.task_runner import run_task_models
from services.task_files import get_task_dir
from services.task_state import update_task_execution_status


def run_task_job(task_id: str, threshold: float) -> dict[str, Any]:
    '''顺序执行一个任务的分类和分割推理'''
    job = get_current_job()
    if job is None:
        raise RuntimeError("推理作业必须由 RQ worker 执行")

    task_dir = get_task_dir(SETTINGS.output_dir, task_id)
    update_task_execution_status(
        task_dir,
        JobStatus.RUNNING,
        job_id=job.id,
        queue_name=SETTINGS.task_queue_name,
    )

    try:
        run_result = run_task_models(task_dir, threshold)
    except Exception as exc:
        update_task_execution_status(
            task_dir,
            JobStatus.FAILED,
            job_id=job.id,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise

    task_record = update_task_execution_status(
        task_dir,
        JobStatus.SUCCEEDED,
        job_id=job.id,
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
