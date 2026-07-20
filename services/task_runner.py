'''完整任务推理流程的统一入口'''

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.inference_service import classify, segment
from services.task_files import (
    create_run_dir,
    load_task_image,
)
from services.task_results import (
    persist_model_result,
)


@dataclass(frozen=True)
class TaskRunResult:
    '''一次完整推理生成的输入与两项模型结果'''

    image_path: Path
    classification_result: dict[str, Any]
    segmentation_result: dict[str, Any]


def run_task_models(task_dir: Path, threshold: float) -> TaskRunResult:
    '''顺序执行分类、分割，并将两项结果写入同一任务目录'''
    image_path = load_task_image(task_dir)
    classification_result = persist_model_result(
        task_dir=task_dir,
        image_path=image_path,
        model_name="classification",
        result=classify(image_path),
    )
    run_dir = create_run_dir(task_dir, "segmentation")
    segmentation_result = persist_model_result(
        task_dir=task_dir,
        image_path=image_path,
        model_name="segmentation",
        result=segment(
            image_path=image_path,
            threshold=threshold,
            output_dir=run_dir,
        ),
        run_dir=run_dir,
    )
    return TaskRunResult(
        image_path=image_path,
        classification_result=classification_result,
        segmentation_result=segmentation_result,
    )
