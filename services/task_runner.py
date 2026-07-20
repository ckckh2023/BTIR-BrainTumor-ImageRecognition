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


@dataclass(frozen=True)
class ModelRunResult:
    '''单个模型调用生成的输入与持久化结果。'''

    image_path: Path
    result: dict[str, Any]


def _run_classification(task_dir: Path, image_path: Path) -> dict[str, Any]:
    '''执行分类并写入结果；调用方已负责加载输入图片'''
    return persist_model_result(
        task_dir=task_dir,
        image_path=image_path,
        model_name="classification",
        result=classify(image_path),
    )


def _run_segmentation(
    task_dir: Path,
    image_path: Path,
    threshold: float,
) -> dict[str, Any]:
    '''执行分割并写入结果；调用方已负责加载输入图片。'''
    run_dir = create_run_dir(task_dir, "segmentation")
    return persist_model_result(
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


def run_classification(task_dir: Path) -> ModelRunResult:
    '''执行单任务分类，并持久化分类结果'''
    image_path = load_task_image(task_dir)
    return ModelRunResult(
        image_path=image_path,
        result=_run_classification(task_dir, image_path),
    )


def run_segmentation(task_dir: Path, threshold: float) -> ModelRunResult:
    '''执行单任务分割，并持久化分割结果'''
    image_path = load_task_image(task_dir)
    return ModelRunResult(
        image_path=image_path,
        result=_run_segmentation(task_dir, image_path, threshold),
    )


def run_task_models(task_dir: Path, threshold: float) -> TaskRunResult:
    '''顺序执行分类、分割，并将两项结果写入同一任务目录'''
    image_path = load_task_image(task_dir)
    classification_result = _run_classification(task_dir, image_path)
    segmentation_result = _run_segmentation(task_dir, image_path, threshold)
    return TaskRunResult(
        image_path=image_path,
        classification_result=classification_result,
        segmentation_result=segmentation_result,
    )
