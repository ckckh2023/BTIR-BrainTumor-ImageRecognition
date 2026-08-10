'''分割优先的本地综合结论'''

from __future__ import annotations

import math
from typing import Any


CONSENSUS_VERSION = "dual-model-v2"
HIGH_CONFIDENCE = 0.7


def build_model_consensus(
    classification: dict[str, Any],
    segmentation: dict[str, Any],
) -> dict[str, Any]:
    '''生成双模型综合结论'''
    classification_class = classification.get("class")
    segmentation_detected, volume_mm3, voxel_count = _segmentation_evidence(segmentation)
    positive_probability = _positive_probability(classification, classification_class)
    segmentation_ratio = _segmentation_ratio(segmentation)
    base = {
        "version": CONSENSUS_VERSION,
        "primary_evidence": "segmentation",
        "segmentation_detected": segmentation_detected,
        "segmentation_volume_mm3": volume_mm3,
        "segmentation_voxel_count": voxel_count,
        "segmentation_ratio": segmentation_ratio,
        "classification_positive_probability": positive_probability,
    }

    if classification_class not in {"yes", "no"}:
        return {
            **base,
            "level": "inconclusive",
            "label": "综合结果待确认",
            "consistency": "inconclusive",
            "requires_review": True,
            "summary": "分割模型已完成，但分类结果异常",
        }

    classification_positive = classification_class == "yes"
    if segmentation_detected and classification_positive:
        return {
            **base,
            "level": "high_probability_present",
            "label": "高概率存在肿瘤相关区域",
            "consistency": "consistent",
            "requires_review": False,
            "summary": "分类模型与分割模型的结果相互支持",
        }
    if not segmentation_detected and not classification_positive:
        high_confidence_negative = (
            positive_probability is not None
            and positive_probability <= 1 - HIGH_CONFIDENCE
        )
        return {
            **base,
            "level": (
                "high_probability_absent"
                if high_confidence_negative
                else "likely_absent"
            ),
            "label": (
                "高概率不存在肿瘤相关区域"
                if high_confidence_negative
                else "倾向不存在肿瘤相关区域"
            ),
            "consistency": "consistent",
            "requires_review": False,
            "summary": "分类模型与分割模型均未提示异常区域",
        }
    if segmentation_detected:
        return {
            **base,
            "level": "possible_present",
            "label": "存在肿瘤相关区域的可能",
            "consistency": "conflicting",
            "requires_review": True,
            "summary": "分割模型检出区域，但分类模型倾向正常",
        }
    return {
        **base,
        "level": "possible_present",
        "label": "存在肿瘤相关区域的可能",
        "consistency": "conflicting",
        "requires_review": True,
        "summary": "分类模型提示异常，但分割模型未检出区域",
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


def _segmentation_ratio(segmentation: dict[str, Any]) -> float:
    regions = segmentation.get("regions")
    if not isinstance(regions, dict):
        return 0.0
    total_ratio = sum(
        _nonnegative_number(region.get("ratio")) or 0.0
        for region in regions.values()
        if isinstance(region, dict)
    )
    return round(total_ratio, 8)


def _positive_probability(
    classification: dict[str, Any],
    classification_class: Any,
) -> float | None:
    probabilities = classification.get("probabilities")
    if isinstance(probabilities, dict):
        probability = _probability(probabilities.get("yes"))
        if probability is not None:
            return probability
    confidence = _probability(classification.get("confidence"))
    if confidence is None:
        return None
    if classification_class == "yes":
        return confidence
    if classification_class == "no":
        return round(1 - confidence, 6)
    return None


def _probability(value: Any) -> float | None:
    number = _nonnegative_number(value)
    if number is None or number > 1:
        return None
    return number


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
