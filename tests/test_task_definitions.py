'''任务领域稳定词条的回归测试'''

from __future__ import annotations

import unittest

from core.task_definitions import (
    InputStorageMode,
    JobStatus,
    ModelName,
    TaskArtifact,
    TaskDirectory,
    TaskStatus,
    model_result_filename,
)


class TaskDefinitionTests(unittest.TestCase):
    '''确保枚举值与已发布的接口、目录和文件约定保持一致'''

    def test_status_values_are_stable(self) -> None:
        self.assertEqual(TaskStatus.CREATED.value, "created")
        self.assertEqual(TaskStatus.SUCCEEDED.value, "succeeded")
        self.assertEqual(JobStatus.QUEUED.value, "queued")
        self.assertEqual(JobStatus.FAILED.value, "failed")

    def test_model_and_artifact_values_are_stable(self) -> None:
        self.assertEqual(model_result_filename(ModelName.CLASSIFICATION), "classification.json")
        self.assertEqual(TaskArtifact.SEGMENTATION_RESULT.value, "segmentation.json")
        self.assertEqual(TaskArtifact.FRONTEND_RESULT.value, "frontend_result.json")
        self.assertEqual(TaskDirectory.INPUT.value, "input")
        self.assertEqual(InputStorageMode.AUTO.value, "auto")


if __name__ == "__main__":
    unittest.main()
