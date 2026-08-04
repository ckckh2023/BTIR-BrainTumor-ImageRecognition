'''任务领域稳定词条的回归测试'''

from __future__ import annotations

import unittest

from core.result_contract import FRONTEND_RESULT_SCHEMA_VERSION
from core.task_definitions import (
    ACTIVE_ASYNC_TASK_STATUSES,
    ALL_MODELS,
    ARCHIVABLE_TASK_STATUSES,
    JobStatus,
    ModelName,
    MODEL_RESULT_ARTIFACTS,
    RETRYABLE_TASK_STATUSES,
    TaskArtifact,
    TaskDirectory,
    TaskStatus,
    VOLUME_MODALITIES,
    VolumeModality,
    model_result_filename,
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
        self.assertEqual(RETRYABLE_TASK_STATUSES, {TaskStatus.FAILED})
        self.assertEqual(
            ARCHIVABLE_TASK_STATUSES,
            {TaskStatus.SUCCEEDED, TaskStatus.CANCELED},
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
            task_status_for_completed_models([ModelName.SEGMENTATION]),
            TaskStatus.PARTIAL,
        )
        self.assertEqual(
            ALL_MODELS,
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
        self.assertEqual(
            MODEL_RESULT_ARTIFACTS[ModelName.SEGMENTATION],
            TaskArtifact.SEGMENTATION_RESULT,
        )
        self.assertEqual(TaskArtifact.SEGMENTATION_RESULT.value, "segmentation.json")
        self.assertEqual(TaskArtifact.FRONTEND_RESULT.value, "frontend_result.json")
        self.assertEqual(TaskArtifact.SEGMENTATION_MASK.value, "prediction.nii.gz")
        self.assertEqual(TaskArtifact.ERROR.value, "error.json")
        self.assertEqual(TaskDirectory.INPUT.value, "input")
        self.assertEqual(
            VOLUME_MODALITIES,
            (
                VolumeModality.FLAIR,
                VolumeModality.T1CE,
                VolumeModality.T1,
                VolumeModality.T2,
            ),
        )


if __name__ == "__main__":
    unittest.main()
