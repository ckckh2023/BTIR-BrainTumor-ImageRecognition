'''AI 结构化证据分析'''

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from time import perf_counter
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from contracts.analysis import SupplementaryAnalysisContent
from core.settings import SETTINGS
from services.model_consensus import build_model_consensus


ANALYSIS_PROMPT_VERSION = "ai-analysis-v1"
UNAVAILABLE_MESSAGE = "综合分析服务暂不可用；本地分类和分割结果不受影响。"
DISABLED_MESSAGE = "未启用外部综合分析服务。"
logger = logging.getLogger(__name__)


class SupplementaryAnalysisError(RuntimeError):
    '''外部分析异常'''


@dataclass(frozen=True)
class ProviderResponse:
    content: str
    model: str
    usage: dict[str, int]
    request_id: str | None


class AiAnalysisProvider:
    '''AI 分析客户端'''

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: int,
        max_retries: int,
        max_tokens: int,
        temperature: float,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.max_tokens = max_tokens
        self.temperature = temperature

    def analyze(self, evidence: dict[str, Any]) -> ProviderResponse:
        if not self.api_key:
            raise SupplementaryAnalysisError("AI API key is not configured")
        if not self.base_url or not self.model:
            raise SupplementaryAnalysisError("AI endpoint or model is not configured")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {
                    "role": "user",
                    "content": "以下是经过脱敏和字段白名单处理的证据 JSON：\n"
                    + json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        request = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    return _parse_provider_response(body, response.headers.get("x-request-id"))
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {408, 409, 429} and exc.code < 500:
                    break
            except (URLError, TimeoutError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                last_error = exc
            if attempt == self.max_retries:
                break
        raise SupplementaryAnalysisError("AI request failed") from last_error


def run_supplementary_analysis(
    classification_result: dict[str, Any],
    segmentation_result: dict[str, Any],
) -> dict[str, Any]:
    '''生成补充分析结果'''
    if not SETTINGS.ai_analysis_enabled:
        return {"status": "disabled", "message": DISABLED_MESSAGE}

    started_at = perf_counter()
    try:
        evidence = build_supplementary_evidence(classification_result, segmentation_result)
        provider = AiAnalysisProvider(
            api_key=SETTINGS.ai_api_key,
            base_url=SETTINGS.ai_base_url,
            model=SETTINGS.ai_model,
            timeout_seconds=SETTINGS.ai_timeout_seconds,
            max_retries=SETTINGS.ai_max_retries,
            max_tokens=SETTINGS.ai_max_tokens,
            temperature=SETTINGS.ai_temperature,
        )
        response = provider.analyze(evidence)
        content = SupplementaryAnalysisContent.model_validate(json.loads(response.content))
    except Exception:
        return {
            "status": "unavailable",
            "provider": "ai",
            "message": UNAVAILABLE_MESSAGE,
            "duration_ms": _elapsed_ms(started_at),
        }

    result: dict[str, Any] = {
        "status": "succeeded",
        "provider": "ai",
        "model": response.model,
        "prompt_version": ANALYSIS_PROMPT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "duration_ms": _elapsed_ms(started_at),
        "content": content.model_dump(mode="json"),
    }
    if response.usage:
        result["usage"] = response.usage
    logger.info(
        "AI analysis succeeded provider=ai model=%s prompt_version=%s duration_ms=%s usage=%s request_id=%s",
        response.model,
        ANALYSIS_PROMPT_VERSION,
        result["duration_ms"],
        response.usage,
        response.request_id,
    )
    return result


def build_supplementary_evidence(
    classification_result: dict[str, Any],
    segmentation_result: dict[str, Any],
) -> dict[str, Any]:
    '''提取脱敏量化证据'''
    classification = _mapping(classification_result.get("classification"), "classification")
    regions = _mapping(segmentation_result.get("regions"), "segmentation.regions")
    evidence_regions: dict[str, dict[str, float | int]] = {}
    for label in ("1", "2", "4"):
        region = regions.get(label)
        if not isinstance(region, dict):
            continue
        allowed = _numeric_fields(
            region,
            ("volume_mm3", "ratio", "share_of_non_background"),
        )
        voxel_count = _integer_or_none(region.get("voxels"))
        if voxel_count is None:
            voxel_count = _integer_or_none(region.get("voxel_count"))
        if voxel_count is not None:
            allowed["voxel_count"] = voxel_count
        if allowed:
            evidence_regions[label] = allowed

    composite_regions = _composite_region_evidence(
        _mapping_or_empty(segmentation_result.get("composites"))
    )

    total_voxel_count = sum(
        int(region.get("voxel_count", 0))
        for region in evidence_regions.values()
    )
    total_volume_mm3 = round(
        sum(float(region.get("volume_mm3", 0.0)) for region in evidence_regions.values()),
        3,
    )
    total_ratio = round(
        sum(float(region.get("ratio", 0.0)) for region in evidence_regions.values()),
        6,
    )
    morphology = _morphology_evidence(
        _mapping_or_empty(segmentation_result.get("morphology"))
    )

    evidence_slices = classification.get("evidence_slices")
    slices: list[dict[str, int | float]] = []
    if isinstance(evidence_slices, list):
        for item in evidence_slices[:5]:
            if isinstance(item, dict):
                allowed = _numeric_fields(item, ("slice_index", "yes_probability"))
                if allowed:
                    slices.append(allowed)
    probability_series = _slice_probability_series(
        classification.get("slice_probability_series")
    )
    probability_histogram = _probability_histogram_evidence(
        classification.get("probability_histogram")
    )
    threshold = _number_or_none(classification.get("threshold"))
    yes_probability = _number_or_none(
        _mapping_or_empty(classification.get("probabilities")).get("yes")
    )
    threshold_margin = _number_or_none(classification.get("threshold_margin"))
    if threshold_margin is None and threshold is not None and yes_probability is not None:
        threshold_margin = round(float(yes_probability) - float(threshold), 6)

    model_consensus = build_model_consensus(
        {"model": classification_result.get("model"), **classification},
        segmentation_result,
    )

    return {
        "evidence_version": "1",
        "classification": {
            "model": _string_or_unknown(classification_result.get("model")),
            "class": _string_or_unknown(classification.get("class")),
            "confidence": _number_or_none(classification.get("confidence")),
            "probabilities": _numeric_fields(
                _mapping_or_empty(classification.get("probabilities")),
                ("yes", "no"),
            ),
            "probability_statistics": _numeric_fields(
                _mapping_or_empty(classification.get("probability_statistics")),
                (
                    "mean_yes_probability",
                    "stddev_yes_probability",
                    "min_yes_probability",
                    "max_yes_probability",
                    "median_yes_probability",
                    "positive_slice_ratio",
                ),
            ),
            "threshold": _number_or_none(classification.get("threshold")),
            "threshold_margin": threshold_margin,
            "positive_slice_structure": _numeric_fields(
                _mapping_or_empty(classification.get("positive_slice_structure")),
                (
                    "positive_runs",
                    "longest_positive_run_samples",
                    "positive_span_samples",
                ),
            ),
            "modality": _string_or_unknown(classification.get("modality")),
            "evaluated_slices": _integer_or_none(classification.get("evaluated_slices")),
            "positive_slices": _integer_or_none(classification.get("positive_slices")),
            "evidence_slices": slices,
            "slice_probability_series": probability_series,
            "probability_histogram": probability_histogram,
            "input_summary": {
                "canonical_shape": _numeric_vector(classification.get("canonical_shape")),
                "foreground_slices": _integer_or_none(
                    classification.get("foreground_slices")
                ),
                "intensity_window": _numeric_pair(classification.get("intensity_window")),
            },
            "experimental": bool(classification.get("experimental", True)),
        },
        "segmentation": {
            "model": _string_or_unknown(segmentation_result.get("model")),
            "spatial": {
                "shape": _numeric_vector(
                    _mapping_or_empty(segmentation_result.get("spatial")).get("shape")
                ),
                "voxel_spacing_mm": _numeric_vector(
                    _mapping_or_empty(segmentation_result.get("spatial")).get("voxel_spacing_mm")
                ),
            },
            "regions": evidence_regions,
            "composites": composite_regions,
            "detected_region_labels": sorted(evidence_regions),
            "non_background_voxel_count": total_voxel_count,
            "non_background_volume_mm3": total_volume_mm3,
            "non_background_ratio": total_ratio,
            "morphology": morphology,
        },
        "local_consensus": model_consensus,
    }


def _system_prompt() -> str:
    return """你是脑 MRI 模型结果的综合说明助手。只根据用户提供的证据 JSON 输出 JSON。
面向用户和评审，先给出清晰、直截了当的“模型综合结论”，不要使用空泛的“无法判断”。
当分类为 yes 且分割的 non_background_voxel_count 大于 0 时，summary 应明确表述“模型结果提示存在肿瘤相关异常区域”，并引用分类概率和分割总体积或占比；follow_up 应建议结合原始多模态 MRI 和掩码进行针对性影像复核，并在有既往检查时进行同部位对比。
当分类为 no 且 non_background_voxel_count 为 0 时，summary 应明确表述“模型结果未提示明显肿瘤相关区域”；follow_up 应建议结合症状和既往检查进行常规随访，症状持续或加重时进行专业影像评估。
当分类与分割不一致时，follow_up 应建议优先复核掩码、最高概率切片和输入质量，必要时补充人工影像评估。
只有在分类与分割不一致、数值缺失或置信度接近阈值时，才使用 inconclusive/conflicting 并说明具体原因。
不要声称查看过原始影像，不要补造数值、肿瘤分型、病灶位置、分期或治疗方案。
输出必须是 JSON 对象，且只能包含以下字段：
{
  "summary": "一至两句直接的模型综合结论，优先引用概率和总体积/占比",
  "observations": ["最多五项，仅复述或比较输入数值；可使用完整切片概率曲线、阳性连续性、阈值差值、概率直方图、输入覆盖度、WT/TC/ET 复合区域、体素间距和分割形态摘要"],
  "consistency": "consistent | inconclusive | conflicting",
  "uncertainties": ["仅在证据不一致或不足时填写"],
  "follow_up": "必须给出一至两句可执行的影像复核、历史对比或随访建议；不生成治疗方案"
}"""


def _parse_provider_response(body: dict[str, Any], request_id: str | None) -> ProviderResponse:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise SupplementaryAnalysisError("AI response has no choice")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise SupplementaryAnalysisError("AI response content is empty")
    usage = _numeric_fields(_mapping_or_empty(body.get("usage")), (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ))
    return ProviderResponse(
        content=content,
        model=_string_or_unknown(body.get("model")),
        usage={name: int(value) for name, value in usage.items()},
        request_id=request_id,
    )


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def _mapping_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _numeric_fields(value: dict[str, Any], names: tuple[str, ...]) -> dict[str, float | int]:
    return {
        name: number
        for name in names
        if (number := _finite_number(value.get(name))) is not None
    }


def _morphology_evidence(value: dict[str, Any]) -> dict[str, int | float | list[int] | list[float]]:
    evidence: dict[str, int | float | list[int] | list[float]] = {}
    evidence.update(
        _numeric_fields(
            value,
            (
                "connected_components",
                "largest_component_voxels",
                "largest_component_volume_mm3",
                "largest_component_ratio",
                "bounding_box_fill_ratio",
            ),
        )
    )
    for name in (
        "bounding_box_size_voxels",
        "bounding_box_size_mm",
        "centroid_normalized",
    ):
        vector = _numeric_vector(value.get(name))
        if vector:
            evidence[name] = vector
    return evidence


def _composite_region_evidence(value: dict[str, Any]) -> dict[str, dict[str, int | float]]:
    composites: dict[str, dict[str, int | float]] = {}
    for name in ("WT", "TC", "ET"):
        composite = value.get(name)
        if not isinstance(composite, dict):
            continue
        allowed = _numeric_fields(
            composite,
            ("volume_mm3", "ratio", "share_of_non_background"),
        )
        voxel_count = _integer_or_none(composite.get("voxels"))
        if voxel_count is not None:
            allowed["voxel_count"] = voxel_count
        if allowed:
            composites[name] = allowed
    return composites


def _slice_probability_series(value: Any) -> list[dict[str, int | float]]:
    if not isinstance(value, list):
        return []
    series: list[dict[str, int | float]] = []
    for item in value[:32]:
        if not isinstance(item, dict):
            continue
        slice_index = _integer_or_none(item.get("slice_index"))
        probability = _number_or_none(item.get("yes_probability"))
        if slice_index is not None and probability is not None:
            series.append({"slice_index": slice_index, "yes_probability": probability})
    return series


def _probability_histogram_evidence(value: Any) -> list[dict[str, int | float]]:
    if not isinstance(value, list):
        return []
    histogram: list[dict[str, int | float]] = []
    for item in value[:8]:
        if not isinstance(item, dict):
            continue
        lower = _number_or_none(item.get("lower"))
        upper = _number_or_none(item.get("upper"))
        count = _integer_or_none(item.get("count"))
        if lower is not None and upper is not None and count is not None:
            histogram.append({"lower": lower, "upper": upper, "count": count})
    return histogram


def _numeric_vector(value: Any) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 3:
        return []
    numbers = [_finite_number(item) for item in value]
    if any(item is None for item in numbers):
        return []
    return [item for item in numbers if item is not None]


def _numeric_pair(value: Any) -> list[int | float]:
    if not isinstance(value, list) or len(value) != 2:
        return []
    numbers = [_finite_number(item) for item in value]
    if any(item is None for item in numbers):
        return []
    return [item for item in numbers if item is not None]


def _finite_number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return value


def _number_or_none(value: Any) -> float | int | None:
    return _finite_number(value)


def _integer_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_or_unknown(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else "unknown"


def _elapsed_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 3)
