'''把三维 NIfTI 转换为二维切片，并聚合切片分类结果'''

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any, Sequence

import nibabel as nib
import numpy as np
from PIL import Image
from PIL.Image import Image as PilImage


@dataclass(frozen=True)
class PreparedVolumeSlices:
    '''一次体积分类使用的标准化轴向切片'''

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
    '''读取 NIfTI，转为 RAS+ 后均匀抽取包含脑组织的轴向切片'''
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


def aggregate_slice_predictions(
    slice_indices: Sequence[int],
    predictions: Sequence[dict[str, Any]],
    *,
    modality: str,
    top_fraction: float,
) -> dict[str, Any]:
    '''以肿瘤概率最高的一组切片生成患者级实验性分类结果'''
    if len(slice_indices) != len(predictions) or not predictions:
        raise ValueError("切片索引和分类结果数量必须一致且不能为空")
    if not 0 < top_fraction <= 1:
        raise ValueError("top_fraction 必须位于 (0, 1]")

    yes_scores: list[float] = []
    probability_rows: list[dict[str, float]] = []
    for prediction in predictions:
        probabilities = prediction.get("probabilities")
        if not isinstance(probabilities, dict) or not {"yes", "no"} <= set(
            probabilities
        ):
            raise ValueError("3D 切片分类要求模型提供 yes/no 概率")
        row = {
            name: float(value)
            for name, value in probabilities.items()
        }
        if any(not 0 <= value <= 1 for value in row.values()):
            raise ValueError("分类概率必须位于 0 到 1 之间")
        probability_rows.append(row)
        yes_scores.append(row["yes"])

    top_k = max(1, ceil(len(predictions) * top_fraction))
    ranked_positions = sorted(
        range(len(predictions)),
        key=yes_scores.__getitem__,
        reverse=True,
    )
    top_positions = ranked_positions[:top_k]
    class_names = list(probability_rows[0])
    aggregated_probabilities = {
        class_name: round(
            sum(probability_rows[position][class_name] for position in top_positions)
            / top_k,
            6,
        )
        for class_name in class_names
    }
    predicted_class = max(
        aggregated_probabilities,
        key=aggregated_probabilities.__getitem__,
    )
    evidence = [
        {
            "slice_index": int(slice_indices[position]),
            "yes_probability": round(yes_scores[position], 6),
        }
        for position in top_positions[:5]
    ]
    return {
        "class": predicted_class,
        "class_id": class_names.index(predicted_class),
        "confidence": aggregated_probabilities[predicted_class],
        "probabilities": aggregated_probabilities,
        "method": "2d_slice_ensemble",
        "experimental": True,
        "modality": modality,
        "axis": "axial",
        "evaluated_slices": len(predictions),
        "positive_slices": sum(
            row["yes"] >= row["no"]
            for row in probability_rows
        ),
        "aggregation": "top_fraction_mean",
        "top_fraction": top_fraction,
        "top_k": top_k,
        "evidence_slices": evidence,
    }


def _sample_evenly(indices: np.ndarray, limit: int) -> np.ndarray:
    if indices.size <= limit:
        return indices
    positions = np.linspace(0, indices.size - 1, num=limit)
    return indices[np.rint(positions).astype(np.int64)]


def _slice_to_rgb(
    slice_data: np.ndarray,
    lower: float,
    upper: float,
) -> PilImage:
    normalized = np.clip((slice_data - lower) / (upper - lower), 0.0, 1.0)
    pixels = np.rint(normalized * 255).astype(np.uint8)
    return Image.fromarray(pixels, mode="L").convert("RGB")
