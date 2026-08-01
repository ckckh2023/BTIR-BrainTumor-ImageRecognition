'''前端推理结果的稳定协议定义与运行时校验'''

from __future__ import annotations

from typing import Any

from core.task_definitions import AnalysisMode, ModelName, TaskStatus


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

    mode = AnalysisMode(payload["analysis_mode"])
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
                "segmentation 缺少模式字段："
                + ", ".join(missing_mode_fields)
            )


def _require_nonempty_string(
    payload: dict[str, Any],
    key: str,
    location: str,
) -> None:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{location}.{key} 必须是非空字符串")
