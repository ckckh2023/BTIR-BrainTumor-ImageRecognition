'''完整任务推理流程的统一入口'''

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from collections.abc import Callable
from typing import Any

from core.task_definitions import AnalysisMode, ModelName
from repositories.task_repository import task_repository
from services.inference_service import classify, segment, segment_volume
from services.task_files import (
    create_run_dir,
    load_task_image,
    load_task_modalities,
)
from services.task_results import (
    persist_model_result,
)


@dataclass(frozen=True)
class TaskRunResult:
    '''一次完整推理生成的输入与两项模型结果'''

    image_path: Path
    classification_result: dict[str, Any] | None
    segmentation_result: dict[str, Any]
    total_inference_ms: float


@dataclass(frozen=True)
class ModelRunResult:
    '''单个模型调用生成的输入与持久化结果'''

    image_path: Path
    result: dict[str, Any]


class TaskCancellationRequested(RuntimeError):
    '''任务在两个模型之间收到取消请求'''


def _run_classification(task_dir: Path, image_path: Path) -> dict[str, Any]:
    '''执行分类并写入结果；调用方已负责加载输入图片'''
    started_at = perf_counter()
    result = classify(image_path)
    result["timing"] = {"inference_ms": _elapsed_ms(started_at)}
    return persist_model_result(
        task_dir=task_dir,
        image_path=image_path,
        model_name=ModelName.CLASSIFICATION,
        result=result,
    )


def _run_segmentation(
    task_dir: Path,
    image_path: Path,
    threshold: float,
) -> dict[str, Any]:
    '''执行分割并写入结果；调用方已负责加载输入图片'''
    run_dir = create_run_dir(task_dir, ModelName.SEGMENTATION)
    started_at = perf_counter()
    result = segment(
        image_path=image_path,
        threshold=threshold,
        output_dir=run_dir,
    )
    result["timing"] = {"inference_ms": _elapsed_ms(started_at)}
    return persist_model_result(
        task_dir=task_dir,
        image_path=image_path,
        model_name=ModelName.SEGMENTATION,
        result=result,
        run_dir=run_dir,
    )


def _run_volume_segmentation(
    task_dir: Path,
    modality_paths: dict[str, Path],
) -> dict[str, Any]:
    '''执行并持久化四模态三维分割'''

    run_dir = create_run_dir(task_dir, ModelName.SEGMENTATION)
    started_at = perf_counter()
    result = segment_volume(
        modality_paths=modality_paths,
        output_dir=run_dir,
    )
    result["timing"] = {"inference_ms": _elapsed_ms(started_at)}
    return persist_model_result(
        task_dir=task_dir,
        image_path=task_dir / "input",
        model_name=ModelName.SEGMENTATION,
        result=result,
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


def run_task_models(
    task_dir: Path,
    threshold: float,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> TaskRunResult:
    '''顺序执行分类、分割，并将两项结果写入同一任务目录'''
    started_at = perf_counter()
    task_record = task_repository.load(task_dir)
    if task_record.analysis_mode is AnalysisMode.THREE_D:
        modality_paths = load_task_modalities(task_dir)
        if progress_callback is not None:
            progress_callback("3D 分割推理中", 0)
        if should_cancel is not None and should_cancel():
            raise TaskCancellationRequested("任务已在 3D 分割开始前取消")
        segmentation_result = _run_volume_segmentation(
            task_dir,
            modality_paths,
        )
        if progress_callback is not None:
            progress_callback("3D 分割完成", 100)
        return TaskRunResult(
            image_path=task_dir / "input",
            classification_result=None,
            segmentation_result=segmentation_result,
            total_inference_ms=_elapsed_ms(started_at),
        )

    image_path = load_task_image(task_dir)
    if progress_callback is not None:
        progress_callback("分类推理中", 0)
    classification_result = _run_classification(task_dir, image_path)
    if progress_callback is not None:
        progress_callback("分类完成，开始分割", 50)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在分类完成后取消")
    segmentation_result = _run_segmentation(task_dir, image_path, threshold)
    if progress_callback is not None:
        progress_callback("推理完成", 100)
    return TaskRunResult(
        image_path=image_path,
        classification_result=classification_result,
        segmentation_result=segmentation_result,
        total_inference_ms=_elapsed_ms(started_at),
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
