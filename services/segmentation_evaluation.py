'''BraTS 四模态三维分割的可重复评测服务'''

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any
import re

import nibabel as nib
import numpy as np


EVALUATION_SCHEMA_VERSION = "1.0"
MODALITIES = ("flair", "t1ce", "t1", "t2")
REGION_LABELS = {
    "WT": frozenset({1, 2, 4}),
    "TC": frozenset({1, 4}),
    "ET": frozenset({4}),
}
ALLOWED_BRATS_LABELS = frozenset({0, 1, 2, 4})
Segmenter = Callable[[dict[str, Path], Path], dict[str, Any]]
ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class BratsSubject:
    subject_id: str
    directory: Path
    modalities: dict[str, Path]
    label_path: Path


def discover_brats_subjects(
    dataset_dir: str | Path,
    *,
    limit: int | None = None,
) -> list[BratsSubject]:
    '''发现数据集根目录下具备四模态和分割标签的受试者目录'''

    root = Path(dataset_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"3D 评测数据集目录不存在：{root}")
    if limit is not None and limit <= 0:
        raise ValueError("limit 必须大于 0")

    subjects: list[BratsSubject] = []
    for subject_dir in sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.name.lower(),
    ):
        nifti_files = sorted(
            path
            for path in subject_dir.iterdir()
            if path.is_file() and _is_nifti(path)
        )
        modalities = {
            modality: _find_unique_file(nifti_files, modality, subject_dir)
            for modality in MODALITIES
        }
        label_path = _find_unique_file(nifti_files, "seg", subject_dir)
        subjects.append(
            BratsSubject(
                subject_id=subject_dir.name,
                directory=subject_dir,
                modalities=modalities,
                label_path=label_path,
            )
        )
        if limit is not None and len(subjects) >= limit:
            break
    if not subjects:
        raise ValueError(f"没有发现可评测的 BraTS 受试者目录：{root}")
    return subjects


def evaluate_brats_segmentation(
    dataset_dir: str | Path,
    *,
    predictions_dir: str | Path | None = None,
    limit: int | None = None,
    segmenter: Segmenter | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    '''逐病例运行真实分割，并汇总 WT、TC、ET Dice 与资源耗时'''

    dataset_root = Path(dataset_dir).expanduser().resolve()
    subjects = discover_brats_subjects(dataset_root, limit=limit)
    segmenter = segmenter or _run_project_segmenter
    persistent_root = (
        Path(predictions_dir).expanduser().resolve()
        if predictions_dir is not None
        else None
    )
    if persistent_root is not None:
        persistent_root.mkdir(parents=True, exist_ok=True)

    report: dict[str, Any] = {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluation": "brats_3d_segmentation",
        "created_at": datetime.now().astimezone().isoformat(),
        "dataset": str(dataset_root),
        "region_definitions": {
            name: sorted(labels)
            for name, labels in REGION_LABELS.items()
        },
        "requested_subjects": len(subjects),
        "successful_subjects": 0,
        "failed_subjects": 0,
        "subjects": [],
    }

    with TemporaryDirectory(prefix="btir-3d-evaluation-") as temporary:
        temporary_root = Path(temporary)
        for index, subject in enumerate(subjects, start=1):
            if progress_callback is not None:
                progress_callback(
                    f"3D 评测 {index}/{len(subjects)}：{subject.subject_id}",
                    round((index - 1) / len(subjects) * 100),
                )
            output_dir = (
                persistent_root / subject.subject_id
                if persistent_root is not None
                else temporary_root / subject.subject_id
            )
            try:
                case_result = _evaluate_subject(
                    subject,
                    output_dir,
                    segmenter,
                    retain_prediction=persistent_root is not None,
                )
            except Exception as exc:
                report["failed_subjects"] += 1
                report["subjects"].append(
                    {
                        "subject_id": subject.subject_id,
                        "status": "failed",
                        "error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                        },
                    }
                )
            else:
                report["successful_subjects"] += 1
                report["subjects"].append(case_result)

    report["summary"] = _summarize_successful_cases(report["subjects"])
    if progress_callback is not None:
        progress_callback("3D 分割评测完成", 100)
    return report


def dice_score(
    prediction: np.ndarray,
    target: np.ndarray,
    labels: frozenset[int],
) -> float | None:
    '''计算一个 BraTS 组合区域的 Dice；双空区域不计入数据集均值'''

    prediction_region = np.isin(prediction, tuple(labels))
    target_region = np.isin(target, tuple(labels))
    denominator = int(prediction_region.sum()) + int(target_region.sum())
    if denominator == 0:
        return None
    intersection = int(np.count_nonzero(prediction_region & target_region))
    return round(2.0 * intersection / denominator, 6)


def _evaluate_subject(
    subject: BratsSubject,
    output_dir: Path,
    segmenter: Segmenter,
    *,
    retain_prediction: bool,
) -> dict[str, Any]:
    _reset_cuda_peak_memory()
    _synchronize_cuda()
    started_at = perf_counter()
    result = segmenter(subject.modalities, output_dir)
    _synchronize_cuda()
    inference_ms = round((perf_counter() - started_at) * 1000, 3)

    prediction_path = Path(result["mask_path"]).expanduser().resolve()
    prediction_image = nib.load(str(prediction_path))
    target_image = nib.load(str(subject.label_path))
    prediction = _validated_brats_labels(prediction_image, "预测掩码")
    target = _validated_brats_labels(target_image, "真值标签")
    _validate_same_space(prediction_image, target_image)

    scores = {
        name: dice_score(prediction, target, labels)
        for name, labels in REGION_LABELS.items()
    }
    case: dict[str, Any] = {
        "subject_id": subject.subject_id,
        "status": "succeeded",
        "label_file": subject.label_path.name,
        "model": result.get("model"),
        "device": result.get("device"),
        "dice": scores,
        "inference_ms": inference_ms,
    }
    if (
        retain_prediction
        and prediction_path.is_relative_to(output_dir.resolve())
    ):
        case["prediction_file"] = prediction_path.relative_to(
            output_dir.parent.resolve()
        ).as_posix()
    peak_memory = _cuda_peak_memory_mb()
    if peak_memory is not None and str(result.get("device", "")).startswith("cuda"):
        case["peak_gpu_memory_mb"] = peak_memory
    return case


def _summarize_successful_cases(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    successful = [case for case in cases if case["status"] == "succeeded"]
    dice_summary: dict[str, Any] = {}
    for region in REGION_LABELS:
        values = [
            float(case["dice"][region])
            for case in successful
            if case["dice"][region] is not None
        ]
        dice_summary[region] = _descriptive_statistics(values)

    inference_values = [
        float(case["inference_ms"])
        for case in successful
    ]
    memory_values = [
        float(case["peak_gpu_memory_mb"])
        for case in successful
        if "peak_gpu_memory_mb" in case
    ]
    return {
        "dice": dice_summary,
        "inference_ms": _descriptive_statistics(inference_values),
        "peak_gpu_memory_mb": _descriptive_statistics(memory_values),
    }


def _descriptive_statistics(values: list[float]) -> dict[str, Any]:
    if not values:
        return {
            "evaluated_cases": 0,
            "mean": None,
            "median": None,
            "min": None,
            "max": None,
        }
    return {
        "evaluated_cases": len(values),
        "mean": round(mean(values), 6),
        "median": round(median(values), 6),
        "min": round(min(values), 6),
        "max": round(max(values), 6),
    }


def _validated_brats_labels(
    image: nib.spatialimages.SpatialImage,
    description: str,
) -> np.ndarray:
    if len(image.shape) != 3:
        raise ValueError(f"{description}必须是三维 NIfTI，收到 {image.shape}")
    values = np.asarray(image.dataobj)
    if not np.isfinite(values).all():
        raise ValueError(f"{description}包含 NaN 或无穷值")
    rounded = np.rint(values)
    if not np.allclose(values, rounded, rtol=0, atol=1e-6):
        raise ValueError(f"{description}包含非整数标签")
    integer_labels = rounded.astype(np.int64)
    unexpected = sorted(
        set(np.unique(integer_labels).tolist()).difference(ALLOWED_BRATS_LABELS)
    )
    if unexpected:
        raise ValueError(
            f"{description}包含 BraTS 0/1/2/4 之外的标签：{unexpected}"
        )
    return integer_labels.astype(np.uint8)


def _validate_same_space(
    prediction: nib.spatialimages.SpatialImage,
    target: nib.spatialimages.SpatialImage,
) -> None:
    if prediction.shape != target.shape:
        raise ValueError(
            f"预测与真值 shape 不一致：{prediction.shape} != {target.shape}"
        )
    if not np.allclose(prediction.affine, target.affine, rtol=1e-5, atol=1e-4):
        raise ValueError("预测与真值 affine 不一致")


def _find_unique_file(
    candidates: list[Path],
    token: str,
    subject_dir: Path,
) -> Path:
    matches = [
        path
        for path in candidates
        if re.search(
            rf"(?:^|[_-]){re.escape(token)}$",
            _strip_nifti_suffix(path.name),
            flags=re.IGNORECASE,
        )
    ]
    if len(matches) != 1:
        names = ", ".join(path.name for path in matches) or "无"
        raise ValueError(
            f"{subject_dir.name} 的 {token} 文件应恰好有一个，当前：{names}"
        )
    return matches[0]


def _strip_nifti_suffix(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".nii.gz"):
        return lowered[:-7]
    if lowered.endswith(".nii"):
        return lowered[:-4]
    return lowered


def _is_nifti(path: Path) -> bool:
    return path.name.lower().endswith((".nii", ".nii.gz"))


def _run_project_segmenter(
    modalities: dict[str, Path],
    output_dir: Path,
) -> dict[str, Any]:
    from services.inference_service import segment_volume

    return segment_volume(modalities, output_dir)


def _reset_cuda_peak_memory() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except (ImportError, RuntimeError):
        return


def _synchronize_cuda() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.synchronize()
    except (ImportError, RuntimeError):
        return


def _cuda_peak_memory_mb() -> float | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return round(torch.cuda.max_memory_allocated() / (1024 * 1024), 3)
    except (ImportError, RuntimeError):
        return None
