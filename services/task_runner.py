'''完整任务推理流程的统一入口'''

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from collections.abc import Callable
from typing import Any

from core.task_definitions import ModelName
from services.inference_service import (
    classify_volume,
    segment_volume,
)
from services.task_files import (
    create_run_dir,
    load_task_modalities,
)
from services.task_results import (
    persist_model_result,
)


@dataclass(frozen=True)
class TaskRunResult:
    '''一次完整推理生成的两项模型结果与总耗时'''

    classification_result: dict[str, Any]
    segmentation_result: dict[str, Any]
    total_inference_ms: float


class TaskCancellationRequested(RuntimeError):
    '''任务在两个模型之间收到取消请求'''


def _run_volume_segmentation(
    task_dir: Path,
    modality_paths: dict[str, Path],
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    '''执行并持久化四模态三维分割'''

    run_dir = create_run_dir(task_dir, ModelName.SEGMENTATION)
    started_at = perf_counter()
    result = segment_volume(
        modality_paths=modality_paths,
        output_dir=run_dir,
        progress_callback=(
            (
                lambda fraction: progress_callback(
                    "3D 分割推理中",
                    min(100, 15 + int(fraction * 85)),
                )
            )
            if progress_callback is not None
            else None
        ),
    )
    result.setdefault("timing", {})["inference_ms"] = _elapsed_ms(started_at)
    return persist_model_result(
        task_dir=task_dir,
        model_name=ModelName.SEGMENTATION,
        result=result,
        run_dir=run_dir,
    )


def _run_volume_classification(
    task_dir: Path,
    modality_paths: dict[str, Path],
) -> dict[str, Any]:
    '''执行并持久化本地 ViT 患者级分类'''
    started_at = perf_counter()
    result = classify_volume(modality_paths)
    result.setdefault("timing", {})["inference_ms"] = _elapsed_ms(started_at)
    return persist_model_result(
        task_dir=task_dir,
        model_name=ModelName.CLASSIFICATION,
        result=result,
    )


def run_task_models(
    task_dir: Path,
    *,
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> TaskRunResult:
    '''顺序执行分类、分割，并将两项结果写入同一任务目录'''
    started_at = perf_counter()
    modality_paths = load_task_modalities(task_dir)
    if progress_callback is not None:
        progress_callback("3D 分类推理中", 0)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在 3D 分类开始前取消")
    classification_result = _run_volume_classification(task_dir, modality_paths)
    if progress_callback is not None:
        progress_callback("3D 分类完成，开始 3D 分割", 15)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在 3D 分类完成后取消")
    segmentation_result = _run_volume_segmentation(
        task_dir,
        modality_paths,
        progress_callback=progress_callback,
    )
    if progress_callback is not None:
        progress_callback("3D 分割完成", 100)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在 3D 分割完成后取消")
    return TaskRunResult(
        classification_result=classification_result,
        segmentation_result=segmentation_result,
        total_inference_ms=_elapsed_ms(started_at),
    )


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
