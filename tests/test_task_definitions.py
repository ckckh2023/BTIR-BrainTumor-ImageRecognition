'''任务领域稳定词条的回归测试'''

from __future__ import annotations

import unittest

from core.result_contract import FRONTEND_RESULT_SCHEMA_VERSION
from core.task_definitions import (
    ACTIVE_ASYNC_TASK_STATUSES,
    AnalysisMode,
    InputStorageMode,
    JobStatus,
    ModelName,
    TaskArtifact,
    TaskDirectory,
    TaskStatus,
    model_result_filename,
    expected_models_for_mode,
    task_status_for_completed_models,
    task_status_from_job_status,
)


class TaskDefinitionTests(unittest.TestCase):
    '''确保枚举值与已发布的接口、目录和文件约定保持一致'''

    def test_status_values_are_stable(self) -> None:
        self.assertEqual(TaskStatus.CREATED.value, "created")
        self.assertEqual(TaskStatus.SUCCEEDED.value, "succeeded")
        self.assertEqual(TaskStatus.CANCEL_REQUESTED.value, "cancel_requested")
        self.assertEqual(TaskStatus.CANCELED.value, "canceled")
        self.assertEqual(JobStatus.QUEUED.value, "queued")
        self.assertEqual(JobStatus.FAILED.value, "failed")
        self.assertEqual(JobStatus.CANCELED.value, "canceled")
        self.assertEqual(
            ACTIVE_ASYNC_TASK_STATUSES,
            {
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.CANCEL_REQUESTED,
            },
        )

    def test_status_helpers_centralize_sync_and_async_transitions(self) -> None:
        self.assertEqual(
            task_status_for_completed_models([ModelName.CLASSIFICATION]),
            TaskStatus.PARTIAL,
        )
        self.assertEqual(
            task_status_for_completed_models(list(ModelName)),
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            task_status_for_completed_models(
                [ModelName.SEGMENTATION],
                [ModelName.SEGMENTATION],
            ),
            TaskStatus.SUCCEEDED,
        )
        self.assertEqual(
            expected_models_for_mode(AnalysisMode.THREE_D),
            {ModelName.CLASSIFICATION, ModelName.SEGMENTATION},
        )
        self.assertEqual(
            task_status_from_job_status(JobStatus.QUEUED),
            TaskStatus.QUEUED,
        )
        self.assertEqual(
            task_status_from_job_status("succeeded"),
            TaskStatus.SUCCEEDED,
        )

    def test_model_and_artifact_values_are_stable(self) -> None:
        self.assertEqual(FRONTEND_RESULT_SCHEMA_VERSION, "1.0")
        self.assertEqual(model_result_filename(ModelName.CLASSIFICATION), "classification.json")
        self.assertEqual(TaskArtifact.SEGMENTATION_RESULT.value, "segmentation.json")
        self.assertEqual(TaskArtifact.FRONTEND_RESULT.value, "frontend_result.json")
        self.assertEqual(TaskDirectory.INPUT.value, "input")
        self.assertEqual(
            tuple(mode.value for mode in AnalysisMode),
            ("2d", "3d"),
        )
        self.assertEqual(
            tuple(mode.value for mode in InputStorageMode),
            ("auto", "hardlink", "copy"),
        )
        with self.assertRaises(ValueError):
            InputStorageMode("reference")


if __name__ == "__main__":
    unittest.main()
