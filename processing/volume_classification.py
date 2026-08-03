"""Prepare 3D NIfTI slices and aggregate the local ViT predictions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median, pstdev
from typing import Any, Mapping, Sequence

import nibabel as nib
import numpy as np
from PIL import Image
from PIL.Image import Image as PilImage


@dataclass(frozen=True)
class PreparedVolumeSlices:
    """Canonical axial slices used for one patient-level classification."""

    images: tuple[PilImage, ...]
    indices: tuple[int, ...]
    canonical_shape: tuple[int, int, int]
    foreground_slice_count: int
    intensity_window: tuple[float, float]


def prepare_volume_slices(
    volume_path: str | Path,
    *,
    max_slices: int,
) -> PreparedVolumeSlices:
    """Load NIfTI as RAS+ and evenly sample informative axial slices."""

    if max_slices <= 0:
        raise ValueError("max_slices 必须大于 0")
    path = Path(volume_path)
    try:
        image = nib.load(str(path))
        canonical = nib.as_closest_canonical(image)
        data = np.asarray(canonical.dataobj, dtype=np.float32)
    except Exception as exc:
        raise ValueError(f"无法读取 3D 分类输入：{path}") from exc

    if data.ndim != 3:
        raise ValueError(f"3D 分类输入必须是三维 NIfTI，收到 shape={data.shape}")
    if not np.isfinite(data).all():
        raise ValueError("3D 分类输入包含 NaN 或无穷值")

    foreground = data != 0
    if not np.any(foreground):
        raise ValueError("3D 分类输入为空体积")

    foreground_counts = foreground.sum(axis=(0, 1))
    minimum_area = max(1, int(foreground_counts.max() * 0.01))
    candidate_indices = np.flatnonzero(foreground_counts >= minimum_area)
    selected_indices = _sample_evenly(candidate_indices, max_slices)

    foreground_values = data[foreground].astype(np.float64, copy=False)
    lower, upper = np.percentile(foreground_values, (1.0, 99.0))
    if not np.isfinite(lower) or not np.isfinite(upper) or upper <= lower:
        raise ValueError("3D 分类输入没有有效的强度变化")

    images = tuple(
        _slice_to_rgb(data[:, :, int(index)], float(lower), float(upper))
        for index in selected_indices
    )
    return PreparedVolumeSlices(
        images=images,
        indices=tuple(int(index) for index in selected_indices),
        canonical_shape=tuple(int(size) for size in data.shape),
        foreground_slice_count=int(candidate_indices.size),
        intensity_window=(round(float(lower), 6), round(float(upper), 6)),
    )


def aggregate_mean_slice_predictions(
    slice_indices: Sequence[int],
    predictions: Sequence[dict[str, Any]],
    *,
    modality: str,
    threshold: float,
) -> dict[str, Any]:
    """Average all slice probabilities into one patient-level prediction."""

    if len(slice_indices) != len(predictions) or not predictions:
        raise ValueError("切片索引和分类结果数量必须一致且不能为空")
    if not 0 < threshold < 1:
        raise ValueError("分类阈值必须位于 (0, 1)")

    yes_scores = [_yes_probability(prediction) for prediction in predictions]
    yes_probability = sum(yes_scores) / len(yes_scores)
    no_probability = 1.0 - yes_probability
    predicted_tumor = yes_probability >= threshold
    positive_slice_count = sum(score >= 0.5 for score in yes_scores)
    ranked_positions = sorted(
        range(len(predictions)),
        key=yes_scores.__getitem__,
        reverse=True,
    )
    positive_runs = _positive_slice_runs(yes_scores, threshold)
    return {
        "class": "yes" if predicted_tumor else "no",
        "class_id": 1 if predicted_tumor else 0,
        "label": "tumor" if predicted_tumor else "healthy",
        "confidence": round(
            yes_probability if predicted_tumor else no_probability,
            6,
        ),
        "probabilities": {
            "no": round(no_probability, 6),
            "yes": round(yes_probability, 6),
        },
        "threshold": round(threshold, 6),
        "method": "vit_binary_multislice_mean",
        "experimental": True,
        "modality": modality,
        "axis": "axial",
        "evaluated_slices": len(predictions),
        "positive_slices": positive_slice_count,
        "probability_statistics": {
            "mean_yes_probability": round(yes_probability, 6),
            "stddev_yes_probability": round(pstdev(yes_scores), 6),
            "min_yes_probability": round(min(yes_scores), 6),
            "max_yes_probability": round(max(yes_scores), 6),
            "median_yes_probability": round(float(median(yes_scores)), 6),
            "positive_slice_ratio": round(
                positive_slice_count / len(yes_scores),
                6,
            ),
        },
        "threshold_margin": round(yes_probability - threshold, 6),
        "positive_slice_structure": {
            "positive_runs": len(positive_runs),
            "longest_positive_run_samples": max(positive_runs, default=0),
            "positive_span_samples": (
                max((index for index, score in enumerate(yes_scores) if score >= threshold), default=-1)
                - min((index for index, score in enumerate(yes_scores) if score >= threshold), default=0)
                + 1
                if positive_runs
                else 0
            ),
        },
        "probability_histogram": _probability_histogram(yes_scores),
        "slice_probability_series": [
            {
                "slice_index": int(slice_index),
                "yes_probability": round(score, 6),
            }
            for slice_index, score in zip(slice_indices, yes_scores, strict=True)
        ],
        "aggregation": "mean_probability",
        "evidence_slices": [
            {
                "slice_index": int(slice_indices[position]),
                "yes_probability": round(yes_scores[position], 6),
            }
            for position in ranked_positions[:5]
        ],
    }


def _sample_evenly(indices: np.ndarray, limit: int) -> np.ndarray:
    if indices.size <= limit:
        return indices
    positions = np.linspace(0, indices.size - 1, num=limit)
    return indices[np.rint(positions).astype(np.int64)]


def _probability_histogram(yes_scores: Sequence[float]) -> list[dict[str, float | int]]:
    edges = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
    return [
        {
            "lower": lower,
            "upper": upper,
            "count": sum(
                lower <= score < upper if upper < 1.0 else lower <= score <= upper
                for score in yes_scores
            ),
        }
        for lower, upper in zip(edges, edges[1:])
    ]


def _positive_slice_runs(yes_scores: Sequence[float], threshold: float) -> list[int]:
    runs: list[int] = []
    current_run = 0
    for score in yes_scores:
        if score >= threshold:
            current_run += 1
        elif current_run:
            runs.append(current_run)
            current_run = 0
    if current_run:
        runs.append(current_run)
    return runs


def _yes_probability(prediction: Mapping[str, Any]) -> float:
    probabilities = prediction.get("probabilities")
    if not isinstance(probabilities, Mapping) or "yes" not in probabilities:
        raise ValueError("切片分类结果缺少 yes 概率")
    score = float(probabilities["yes"])
    if not 0 <= score <= 1:
        raise ValueError("切片分类概率必须位于 0 到 1 之间")
    return score


def _slice_to_rgb(
    slice_data: np.ndarray,
    lower: float,
    upper: float,
) -> PilImage:
    normalized = np.clip((slice_data - lower) / (upper - lower), 0.0, 1.0)
    pixels = np.rint(normalized * 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="L").convert("RGB")
