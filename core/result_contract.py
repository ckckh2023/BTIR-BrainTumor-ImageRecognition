'''前端推理结果的稳定协议定义与运行时校验'''

from __future__ import annotations

from typing import Any

from core.task_definitions import ModelName, TaskStatus


FRONTEND_RESULT_SCHEMA_VERSION = "1.0"
LEGACY_MODEL_NAME = "legacy/unknown"


def upgrade_frontend_result(payload: dict[str, Any]) -> dict[str, Any]:
    '''以向后兼容方式补齐旧结果缺少的协议元数据'''

    payload["schema_version"] = FRONTEND_RESULT_SCHEMA_VERSION
    classification = payload.get("classification")
    if isinstance(classification, dict):
        classification.setdefault("model", LEGACY_MODEL_NAME)
    return payload


def validate_frontend_result(payload: dict[str, Any]) -> None:
    '''校验新生成结果的稳定字段，模型适配器不得改变这些字段语义'''

    required = {
        "schema_version",
        "task_id",
        "created_at",
        "updated_at",
        "analysis_mode",
        "status",
        "completed_models",
        "result_files",
        "latest_runs",
    }
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"前端结果缺少协议字段：{', '.join(missing)}")
    if payload["schema_version"] != FRONTEND_RESULT_SCHEMA_VERSION:
        raise ValueError(
            "前端结果协议版本不受支持："
            f"{payload['schema_version']!r}"
        )

    if payload["analysis_mode"] != "3d":
        raise ValueError("analysis_mode 必须是 3d")
    TaskStatus(payload["status"])
    completed_models = payload["completed_models"]
    if not isinstance(completed_models, list):
        raise ValueError("completed_models 必须是列表")
    for model in completed_models:
        ModelName(model)
    if not isinstance(payload["result_files"], dict):
        raise ValueError("result_files 必须是对象")
    if not isinstance(payload["latest_runs"], dict):
        raise ValueError("latest_runs 必须是对象")

    input_files = payload.get("input_files")
    if not isinstance(input_files, dict):
        raise ValueError("3D 结果的 input_files 必须是对象")

    classification = payload.get("classification")
    if classification is not None:
        if not isinstance(classification, dict):
            raise ValueError("classification 必须是对象")
        for key in ("model", "class", "confidence"):
            if key not in classification:
                raise ValueError(f"classification 缺少字段：{key}")
        _require_nonempty_string(classification, "model", "classification")
        _require_nonempty_string(classification, "class", "classification")
        confidence = classification["confidence"]
        if (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise ValueError("classification.confidence 必须位于 0 到 1 之间")

    segmentation = payload.get("segmentation")
    if segmentation is not None:
        if not isinstance(segmentation, dict):
            raise ValueError("segmentation 必须是对象")
        for key in ("model", "mask_file"):
            _require_nonempty_string(segmentation, key, "segmentation")
        mode_fields = ("spatial", "labels", "regions")
        missing_mode_fields = [
            key for key in mode_fields if key not in segmentation
        ]
        if missing_mode_fields:
            raise ValueError(
                "segmentation 缺少 3D 结果字段："
                + ", ".join(missing_mode_fields)
            )

    model_consensus = payload.get("model_consensus")
    if model_consensus is not None:
        _validate_model_consensus(model_consensus)

    supplementary_analysis = payload.get("supplementary_analysis")
    if supplementary_analysis is not None:
        _validate_supplementary_analysis(supplementary_analysis)


def _validate_supplementary_analysis(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("supplementary_analysis 必须是对象")
    status = value.get("status")
    if status not in {"disabled", "unavailable", "succeeded"}:
        raise ValueError("supplementary_analysis.status 无效")
    if status != "succeeded":
        return
    for key in ("provider", "model", "prompt_version", "generated_at"):
        _require_nonempty_string(value, key, "supplementary_analysis")
    content = value.get("content")
    if not isinstance(content, dict):
        raise ValueError("supplementary_analysis.content 必须是对象")
    for key in ("summary", "observations", "consistency", "uncertainties", "follow_up"):
        if key not in content:
            raise ValueError(f"supplementary_analysis.content 缺少字段：{key}")
    if content["consistency"] not in {"consistent", "inconclusive", "conflicting"}:
        raise ValueError("supplementary_analysis.content.consistency 无效")
    if not isinstance(content["observations"], list) or not isinstance(content["uncertainties"], list):
        raise ValueError("supplementary_analysis.content 列表字段无效")


def _validate_model_consensus(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("model_consensus 必须是对象")
    for key in ("version", "level", "label", "summary", "consistency", "primary_evidence"):
        _require_nonempty_string(value, key, "model_consensus")
    if value["level"] not in {
        "high_probability_present",
        "possible_present",
        "likely_absent",
        "high_probability_absent",
        "inconclusive",
    }:
        raise ValueError("model_consensus.level 无效")
    if value["consistency"] not in {"consistent", "inconclusive", "conflicting"}:
        raise ValueError("model_consensus.consistency 无效")
    if value["primary_evidence"] != "segmentation":
        raise ValueError("model_consensus.primary_evidence 无效")
    for key in ("requires_review", "segmentation_detected"):
        if not isinstance(value.get(key), bool):
            raise ValueError(f"model_consensus.{key} 必须是布尔值")
    for key in ("segmentation_volume_mm3", "segmentation_ratio"):
        value_number = value.get(key)
        if isinstance(value_number, bool) or not isinstance(value_number, (int, float)):
            raise ValueError(f"model_consensus.{key} 必须是数字")


def _require_nonempty_string(
    payload: dict[str, Any],
    key: str,
    location: str,
) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{key} 必须是非空字符串")
