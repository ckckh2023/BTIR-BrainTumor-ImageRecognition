"""Regression tests for the optional DeepSeek supplementary-analysis route."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

from core.settings import SETTINGS
from services.supplementary_analysis import (
    DeepSeekProvider,
    ProviderResponse,
    build_supplementary_evidence,
    run_supplementary_analysis,
)
from services.task_results import build_frontend_result
from services.task_runner import run_task_models


class SupplementaryAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classification = {
            "model": "models/classification/vit-binary",
            "classification": {
                "class": "yes",
                "confidence": 0.81,
                "probabilities": {"yes": 0.81, "no": 0.19},
                "threshold": 0.5,
                "modality": "flair",
                "evaluated_slices": 25,
                "positive_slices": 14,
                "probability_statistics": {
                    "mean_yes_probability": 0.81,
                    "stddev_yes_probability": 0.08,
                    "min_yes_probability": 0.61,
                    "max_yes_probability": 0.93,
                    "median_yes_probability": 0.82,
                "positive_slice_ratio": 0.56,
                },
                "threshold_margin": 0.31,
                "positive_slice_structure": {
                    "positive_runs": 2,
                    "longest_positive_run_samples": 8,
                    "positive_span_samples": 12,
                },
                "probability_histogram": [{"lower": 0.8, "upper": 1.0, "count": 12}],
                "slice_probability_series": [
                    {"slice_index": 20, "yes_probability": 0.84},
                    {"slice_index": 21, "yes_probability": 0.88},
                ],
                "canonical_shape": [240, 240, 155],
                "foreground_slices": 120,
                "intensity_window": [12.0, 145.0],
                "experimental": True,
                "evidence_slices": [{"slice_index": 37, "yes_probability": 0.93}],
                "task_dir": "must-not-leave-server",
            },
        }
        self.segmentation = {
            "model": "models/segmentation3d/superlightnet",
            "regions": {
                "1": {"voxel_count": 10, "volume_mm3": 12.5, "ratio": 0.02},
                "2": {"voxel_count": 20, "volume_mm3": 25.0, "ratio": 0.04},
            },
            "mask_path": "E:/private/output/task/runs/mask.nii.gz",
            "morphology": {
                "connected_components": 2,
                "largest_component_voxels": 20,
                "largest_component_ratio": 0.67,
                "bounding_box_size_voxels": [4, 5, 6],
                "centroid_normalized": [0.2, 0.3, 0.4],
                "largest_component_volume_mm3": 18.4,
                "bounding_box_size_mm": [4.0, 6.0, 8.0],
                "bounding_box_fill_ratio": 0.5,
            },
            "spatial": {"shape": [100, 120, 80], "voxel_spacing_mm": [1.0, 1.0, 1.5]},
            "composites": {
                "WT": {"voxels": 30, "volume_mm3": 37.5, "ratio": 0.06, "share_of_non_background": 1.0},
                "TC": {"voxels": 10, "volume_mm3": 12.5, "ratio": 0.02, "share_of_non_background": 0.33},
                "ET": {"voxels": 5, "volume_mm3": 6.25, "ratio": 0.01, "share_of_non_background": 0.17},
            },
        }

    def test_provider_sends_only_whitelisted_evidence_and_requests_json(self) -> None:
        response = MagicMock()
        response.read.return_value = json.dumps(
            {
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            }
        ).encode("utf-8")
        response.headers.get.return_value = "request-123"
        provider = DeepSeekProvider(
            api_key="test-key",
            base_url="https://api.deepseek.example",
            model="deepseek-v4-flash",
            timeout_seconds=2,
            max_retries=0,
            max_tokens=200,
            temperature=0.2,
        )

        with patch("services.supplementary_analysis.urlopen") as open_url:
            open_url.return_value.__enter__.return_value = response
            provider.analyze(build_supplementary_evidence(self.classification, self.segmentation))

        request = open_url.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        prompt = payload["messages"][1]["content"]
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("E:/private", prompt)
        self.assertNotIn("must-not-leave-server", prompt)
        self.assertNotIn("mask_path", prompt)
        self.assertNotIn("task_dir", prompt)
        self.assertIn('"volume_mm3":12.5', prompt)

    def test_unavailable_provider_is_a_public_soft_failure(self) -> None:
        settings = replace(
            SETTINGS,
            supplementary_analysis_enabled=True,
            deepseek_api_key="test-key",
            supplementary_analysis_max_retries=0,
        )
        with (
            patch("services.supplementary_analysis.SETTINGS", settings),
            patch(
                "services.supplementary_analysis.DeepSeekProvider.analyze",
                side_effect=RuntimeError("network should not escape"),
            ),
        ):
            result = run_supplementary_analysis(self.classification, self.segmentation)

        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("network should not escape", json.dumps(result))

    def test_successful_response_is_validated_before_it_is_exposed(self) -> None:
        settings = replace(
            SETTINGS,
            supplementary_analysis_enabled=True,
            deepseek_api_key="test-key",
        )
        response = ProviderResponse(
            content=json.dumps(
                {
                    "summary": "模型结果提示存在肿瘤相关异常区域，分类阳性概率为 0.81。",
                    "observations": ["分类阳性概率为 0.81。"],
                    "consistency": "inconclusive",
                    "uncertainties": [],
                    "follow_up": "建议结合原始多模态 MRI 和分割掩码进行针对性影像复核。",
                }
            ),
            model="deepseek-v4-flash",
            usage={"total_tokens": 42},
            request_id="request-123",
        )
        with (
            patch("services.supplementary_analysis.SETTINGS", settings),
            patch("services.supplementary_analysis.DeepSeekProvider.analyze", return_value=response),
        ):
            result = run_supplementary_analysis(self.classification, self.segmentation)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["content"]["consistency"], "inconclusive")
        self.assertIn("影像复核", result["content"]["follow_up"])
        self.assertEqual(result["usage"], {"total_tokens": 42})
        self.assertNotIn("disclaimer", result)

    def test_supplementary_analysis_does_not_change_task_success_semantics(self) -> None:
        task_dir = Path("output") / "task-analysis-contract"
        result = build_frontend_result(
            task_dir,
            classification={
                "model": "classification",
                "classification": {"class": "yes", "confidence": 0.8},
                "run_directory": "runs/classification/run-1",
            },
            segmentation={
                "model": "segmentation",
                "spatial": {},
                "labels": {},
                "regions": {},
                "mask_path": task_dir / "runs" / "segmentation" / "mask.nii.gz",
                "run_directory": "runs/segmentation/run-1",
            },
            supplementary_analysis={
                "status": "unavailable",
                "provider": "deepseek",
                "message": "综合分析服务暂不可用；本地分类和分割结果不受影响。",
                "duration_ms": 2.5,
            },
        )

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["completed_models"], ["classification", "segmentation"])
        self.assertEqual(result["supplementary_analysis"]["status"], "unavailable")
        self.assertEqual(result["timing"]["supplementary_analysis_ms"], 2.5)

    def test_evidence_includes_total_segmentation_measurements(self) -> None:
        evidence = build_supplementary_evidence(self.classification, self.segmentation)

        segmentation = evidence["segmentation"]
        self.assertEqual(segmentation["non_background_voxel_count"], 30)
        self.assertEqual(segmentation["non_background_volume_mm3"], 37.5)
        self.assertEqual(segmentation["non_background_ratio"], 0.06)
        self.assertEqual(evidence["local_consensus"]["consistency"], "consistent")
        self.assertEqual(evidence["local_consensus"]["primary_evidence"], "segmentation")
        self.assertEqual(segmentation["morphology"]["connected_components"], 2)
        self.assertEqual(segmentation["morphology"]["bounding_box_size_voxels"], [4, 5, 6])
        self.assertEqual(segmentation["spatial"]["voxel_spacing_mm"], [1.0, 1.0, 1.5])
        self.assertEqual(segmentation["composites"]["WT"]["volume_mm3"], 37.5)
        self.assertEqual(
            evidence["classification"]["slice_probability_series"][0],
            {"slice_index": 20, "yes_probability": 0.84},
        )
        self.assertEqual(evidence["classification"]["threshold_margin"], 0.31)
        self.assertEqual(
            evidence["classification"]["positive_slice_structure"]["longest_positive_run_samples"],
            8,
        )
        self.assertEqual(evidence["classification"]["input_summary"]["foreground_slices"], 120)
        self.assertEqual(
            evidence["classification"]["probability_statistics"]["stddev_yes_probability"],
            0.08,
        )

    def test_runner_keeps_model_results_when_supplementary_analysis_is_unavailable(self) -> None:
        task_dir = Path("output") / "task-runner-analysis"
        modality_paths = {name: task_dir / "input" / f"{name}.nii.gz" for name in ("flair", "t1ce", "t1", "t2")}
        unavailable = {"status": "unavailable", "message": "服务暂不可用"}
        with (
            patch("services.task_runner.load_task_modalities", return_value=modality_paths),
            patch("services.task_runner.classify_volume", return_value={"classification": {"class": "yes"}}),
            patch("services.task_runner.create_run_dir", return_value=task_dir / "runs" / "segmentation" / "run-1"),
            patch("services.task_runner.segment_volume", return_value={"mask_path": task_dir / "runs" / "segmentation" / "run-1" / "mask.nii.gz"}),
            patch("services.task_runner.persist_model_result", side_effect=[{"model_result_path": "classification.json"}, {"model_result_path": "segmentation.json"}]),
            patch("services.task_runner.run_supplementary_analysis", return_value=unavailable),
            patch("services.task_runner.persist_supplementary_analysis", return_value=unavailable),
        ):
            result = run_task_models(task_dir)

        self.assertEqual(result.classification_result["model_result_path"], "classification.json")
        self.assertEqual(result.segmentation_result["model_result_path"], "segmentation.json")
        self.assertEqual(result.supplementary_analysis["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
