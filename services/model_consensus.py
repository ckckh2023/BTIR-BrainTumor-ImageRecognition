'''分割优先的本地综合结论'''

from __future__ import annotations

import math
from typing import Any


CONSENSUS_VERSION = "segmentation-first-v1"


def build_model_consensus(
    classification: dict[str, Any],
    segmentation: dict[str, Any],
) -> dict[str, Any]:
    '''生成分割优先的结论'''
    classification_class = classification.get("class")
    segmentation_detected, volume_mm3, voxel_count = _segmentation_evidence(segmentation)
    base = {
        "version": CONSENSUS_VERSION,
        "primary_evidence": "segmentation",
        "segmentation_detected": segmentation_detected,
        "segmentation_volume_mm3": volume_mm3,
        "segmentation_voxel_count": voxel_count,
    }

    if classification_class not in {"yes", "no"}:
        return {
            **base,
            "consistency": "inconclusive",
            "requires_review": True,
            "summary": "分割模型已完成，但分类结果异常，建议复核。",
        }

    classification_positive = classification_class == "yes"
    if segmentation_detected and classification_positive:
        return {
            **base,
            "consistency": "consistent",
            "requires_review": False,
            "summary": "模型综合提示存在肿瘤相关异常区域。",
        }
    if not segmentation_detected and not classification_positive:
        return {
            **base,
            "consistency": "consistent",
            "requires_review": False,
            "summary": "模型综合未提示明显肿瘤相关异常区域。",
        }
    if segmentation_detected:
        return {
            **base,
            "consistency": "conflicting",
            "requires_review": True,
            "summary": "检出异常区域，分类模型未提示异常，建议复核。",
        }
    return {
        **base,
        "consistency": "conflicting",
        "requires_review": True,
        "summary": "分类模型提示异常，但未检出明确异常区域，建议复核。",
    }


def _segmentation_evidence(segmentation: dict[str, Any]) -> tuple[bool, float, int]:
    total_volume_mm3 = 0.0
    total_voxel_count = 0
    regions = segmentation.get("regions")
    if not isinstance(regions, dict):
        return False, total_volume_mm3, total_voxel_count
    for region in regions.values():
        if not isinstance(region, dict):
            continue
        volume = _nonnegative_number(region.get("volume_mm3"))
        voxels = _nonnegative_integer(region.get("voxels"))
        if voxels is None:
            voxels = _nonnegative_integer(region.get("voxel_count"))
        total_volume_mm3 += volume or 0.0
        total_voxel_count += voxels or 0
    return (
        total_voxel_count > 0 or total_volume_mm3 > 0,
        round(total_volume_mm3, 3),
        total_voxel_count,
    )


def _nonnegative_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _nonnegative_integer(value: Any) -> int | None:
    number = _nonnegative_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)
