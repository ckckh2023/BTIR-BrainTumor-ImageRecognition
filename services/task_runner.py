'''完整任务推理流程的统一入口'''

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from time import perf_counter
from collections.abc import Callable
from typing import Any

from core.task_definitions import ModelName, TaskArtifact
from services.case_preview import render_case_preview
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
    persist_supplementary_analysis,
)
from services.supplementary_analysis import run_supplementary_analysis


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskRunResult:
    '''一次完整推理生成的两项模型结果与总耗时'''

    classification_result: dict[str, Any]
    segmentation_result: dict[str, Any]
    total_inference_ms: float
    supplementary_analysis: dict[str, Any] = field(
        default_factory=lambda: {"status": "disabled"}
    )


class TaskCancellationRequested(RuntimeError):
    '''任务在两个模型之间收到取消请求'''


def _run_volume_segmentation(
    task_dir: Path,
    modality_paths: dict[str, Path],
    should_cancel: Callable[[], bool] | None = None,
    progress_callback: Callable[[str, int], None] | None = None,
) -> dict[str, Any]:
    '''执行并持久化四模态三维分割'''

    run_dir = create_run_dir(task_dir, ModelName.SEGMENTATION)
    started_at = perf_counter()

    def check_cancellation() -> None:
        if should_cancel is not None and should_cancel():
            raise TaskCancellationRequested("任务已在 3D 分割窗口之间取消")

    def report_progress(fraction: float) -> None:
        if progress_callback is not None:
            progress_callback(
                "3D 分割推理中",
                min(98, 44 + int(fraction * 54)),
            )

    result = segment_volume(
        modality_paths=modality_paths,
        output_dir=run_dir,
        progress_callback=report_progress if progress_callback is not None else None,
        cancel_callback=check_cancellation if should_cancel is not None else None,
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
        progress_callback("3D 分类推理中", 36)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在 3D 分类开始前取消")
    classification_result = _run_volume_classification(task_dir, modality_paths)
    if progress_callback is not None:
        progress_callback("3D 分类完成，开始 3D 分割", 44)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在 3D 分类完成后取消")
    segmentation_result = _run_volume_segmentation(
        task_dir,
        modality_paths,
        should_cancel=should_cancel,
        progress_callback=progress_callback,
    )
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在 3D 分割完成后取消")
    if progress_callback is not None:
        progress_callback("正在生成综合分析", 99)
    supplementary_analysis = run_supplementary_analysis(
        classification_result,
        segmentation_result,
    )
    if supplementary_analysis["status"] != "disabled":
        supplementary_analysis = persist_supplementary_analysis(
            task_dir,
            supplementary_analysis,
        )
    logger.info(
        "supplementary analysis completed task_id=%s status=%s provider=%s model=%s prompt_version=%s duration_ms=%s usage=%s",
        task_dir.name,
        supplementary_analysis.get("status"),
        supplementary_analysis.get("provider"),
        supplementary_analysis.get("model"),
        supplementary_analysis.get("prompt_version"),
        supplementary_analysis.get("duration_ms"),
        supplementary_analysis.get("usage"),
    )
    _render_case_preview(task_dir, modality_paths, segmentation_result)
    if should_cancel is not None and should_cancel():
        raise TaskCancellationRequested("任务已在综合分析完成后取消")
    if progress_callback is not None:
        progress_callback("3D 分割与综合分析完成", 100)
    return TaskRunResult(
        classification_result=classification_result,
        segmentation_result=segmentation_result,
        total_inference_ms=_elapsed_ms(started_at),
        supplementary_analysis=supplementary_analysis,
    )


def _render_case_preview(
    task_dir: Path,
    modality_paths: dict[str, Path],
    segmentation_result: dict[str, Any],
) -> None:
    '''生成四模态切片预览图并登记到前端结果，失败不影响任务结果'''
    mask_relative = segmentation_result.get("mask_file")
    if not mask_relative:
        return
    try:
        preview_path = render_case_preview(
            modality_paths=modality_paths,
            mask_path=task_dir / Path(str(mask_relative)),
            output_path=task_dir / TaskArtifact.PREVIEW,
        )
        if preview_path is None:
            return
        frontend_path = task_dir / TaskArtifact.FRONTEND_RESULT
        if not frontend_path.is_file():
            return
        payload = json.loads(frontend_path.read_text(encoding="utf-8"))
        payload.setdefault("result_files", {})["preview"] = TaskArtifact.PREVIEW
        frontend_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("preview generation failed task_id=%s", task_dir.name)


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
