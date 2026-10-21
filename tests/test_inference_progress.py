'''已发布 1.0.0 客户端的进度接口兼容与实际工作量回归测试。'''

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import torch
from PIL import Image

from core.task_definitions import JobStatus, TaskStatus
from core.task_records import StoredTaskInput, TaskJobRecord, TaskRecord
from models.classification.vit_binary import LoadedBinarySliceClassifier, predict_images
from services import inference_service, task_runner
from services.task_queue import get_task_job_progress
from workers import inference_jobs


def task_record(status=TaskStatus.RUNNING):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return TaskRecord(
        task_id="progress-fixture", name="合成进度测试", status=status,
        created_at=now, updated_at=now,
        input=StoredTaskInput(size_bytes=1, sha256="a" * 64),
        job=TaskJobRecord(id="progress-job", queue="test", status=JobStatus.RUNNING),
    )


class LegacyProgressTests(unittest.TestCase):
    def read_progress(self, metadata, status=TaskStatus.RUNNING):
        with (
            patch("services.task_queue.get_redis_client", return_value=Mock()),
            patch("services.task_queue.Job.fetch", return_value=SimpleNamespace(meta=metadata)),
        ):
            return get_task_job_progress(task_record(status))

    def test_queued_retry_does_not_expose_previous_attempt_98_percent(self):
        value = self.read_progress({"progress": 98, "progress_stage": "上次分割"}, TaskStatus.QUEUED)
        self.assertEqual(value["progress"], 0)
        self.assertIn("排队", value["progress_stage"])

    def test_running_task_cannot_claim_100_before_success(self):
        self.assertEqual(self.read_progress({"progress": 100, "progress_stage": "保存结果"})["progress"], 99)

    def test_invalid_percentages_do_not_break_legacy_status_endpoint(self):
        for value in (float("nan"), float("inf"), True, None, "50"):
            with self.subTest(value=value):
                result = self.read_progress({"progress": value})
                self.assertEqual(result["progress"], 0 if value is None else 36)
                self.assertIsInstance(result["progress_stage"], str)

    def test_old_worker_metadata_without_timestamp_stays_compatible(self):
        self.assertEqual(self.read_progress({"progress": 65, "progress_stage": "3D 分割推理中"}),
                         {"progress": 65, "progress_stage": "3D 分割推理中"})

    def test_slow_cpu_step_updates_text_without_inventing_percentage(self):
        metadata = {"progress": 44, "progress_stage": "3D 分割推理中", "progress_stage_started_at": 100.0}
        with patch("services.inference_progress.time", return_value=110.0):
            first = self.read_progress(metadata)
        with patch("services.inference_progress.time", return_value=113.0):
            second = self.read_progress(metadata)
        self.assertEqual(first["progress"], second["progress"])
        self.assertIn("10秒", first["progress_stage"])
        self.assertIn("13秒", second["progress_stage"])
        self.assertEqual(set(first), {"progress", "progress_stage"})

    def test_stage_clock_is_preserved_for_each_completed_batch(self):
        job = SimpleNamespace(id="progress-clock", meta={}, save_meta=Mock())
        with patch("workers.inference_jobs.time", side_effect=[100.0, 110.0, 120.0]) as clock:
            inference_jobs._record_job_progress(job, "fixture", "分类", 36)
            inference_jobs._record_job_progress(job, "fixture", "分类", 40)
            self.assertEqual(job.meta["progress_stage_started_at"], 100.0)
            inference_jobs._record_job_progress(job, "fixture", "分割", 44)
        self.assertEqual(clock.call_count, 3)
        self.assertEqual(job.meta["progress_stage_started_at"], 120.0)

    def test_new_attempt_resets_progress_but_preserves_cancel_signal(self):
        job = SimpleNamespace(meta={"progress": 98, "progress_stage": "旧阶段",
                                   "progress_stage_started_at": 100, "progress_updated_at": 100,
                                   "progress_display_from": 90, "progress_display_started_at": 100,
                                   "progress_display_duration": 6, "cancel_requested": True},
                              refresh=Mock(), save_meta=Mock())
        inference_jobs._reset_job_progress(job)
        self.assertEqual(job.meta, {"cancel_requested": True})

    def test_elapsed_handles_old_or_invalid_timestamps(self):
        from services.inference_progress import stage_with_elapsed
        for value in (None, True, "date", float("nan"), float("inf"), 9999):
            with self.subTest(value=value):
                self.assertEqual(stage_with_elapsed("加载模型", value, now=100), "加载模型")
        self.assertIn("2分05秒", stage_with_elapsed("加载模型", 100, now=225))


class WorkUnitProgressTests(unittest.TestCase):
    def test_classifier_reports_completed_batches_without_changing_predictions(self):
        class Processor:
            def __call__(self, *, images, return_tensors):
                return {"pixel_values": torch.ones((len(images), 1))}

        class Model(torch.nn.Module):
            def forward(self, *, pixel_values):
                return SimpleNamespace(logits=torch.tensor([[-1.0, 1.0]]).repeat(len(pixel_values), 1))

        loaded = LoadedBinarySliceClassifier(Model(), Processor(), 0, 1, torch.device("cpu"), "fixture")
        images = [Image.new("RGB", (8, 8)) for _ in range(5)]
        expected = predict_images(loaded, images, batch_size=2)
        fractions = []
        actual = predict_images(loaded, images, batch_size=2, progress_callback=fractions.append)
        self.assertEqual(actual, expected)
        self.assertEqual(fractions, [0.4, 0.8, 1.0])

    def test_classification_service_reports_progress_without_exposing_device(self):
        prepared = SimpleNamespace(images=[object(), object()], indices=[1, 2],
                                   canonical_shape=(2, 2, 2), foreground_slice_count=2, intensity_window=(0, 1))
        namespace = {"torch": torch}
        def classify(loaded, images, *, batch_size, progress_callback):
            progress_callback(0.5)
            progress_callback(1.0)
            return [{"probabilities": {"yes": 0.8, "no": 0.2}}] * 2
        namespace["predict_images"] = classify
        fractions, stages = [], []
        with (
            patch.object(inference_service, "prepare_volume_slices", return_value=prepared),
            patch.object(inference_service, "_load_vit_classifier_namespace", return_value=namespace),
            patch.object(inference_service, "resolve_device", return_value=torch.device("cpu")),
            patch.object(inference_service, "_load_vit_classifier_model", return_value=SimpleNamespace(checkpoint_name="fixture")),
        ):
            result = inference_service.classify_volume({"flair": Path("synthetic.nii.gz")},
                                                       progress_callback=fractions.append, stage_callback=stages.append)
        self.assertEqual(fractions, [0.5, 1.0])
        self.assertEqual(result["classification"]["device"], "cpu")
        self.assertIn("加载分类模型", stages)
        self.assertIn("汇总分类结果", stages)

    def test_runner_keeps_legacy_ranges_and_never_finishes_before_persistence(self):
        events = []
        def classify(paths, *, progress_callback, stage_callback):
            stage_callback("加载分类模型")
            stage_callback("3D 分类推理中")
            progress_callback(0.5)
            progress_callback(1.0)
            return {"classification": {"class": "yes"}}
        def segment(*, modality_paths, output_dir, progress_callback, cancel_callback, stage_callback):
            stage_callback("3D 分割推理中")
            for fraction in (0.25, 0.5, 1.0):
                progress_callback(fraction)
            stage_callback("分割结果后处理")
            return {"mask_path": "synthetic.nii.gz"}
        with (
            patch.object(task_runner, "load_task_modalities", return_value={}),
            patch.object(task_runner, "create_run_dir", return_value=Path("synthetic-run")),
            patch.object(task_runner, "classify_volume", side_effect=classify),
            patch.object(task_runner, "segment_volume", side_effect=segment),
            patch.object(task_runner, "persist_model_result", return_value={"model_result_path": "fixture.json"}),
            patch.object(task_runner, "run_supplementary_analysis", return_value={"status": "disabled"}),
            patch.object(task_runner, "_render_case_preview"),
        ):
            task_runner.run_task_models(Path("synthetic-task"), progress_callback=lambda s, p: events.append((s, p)))
        values = [p for _, p in events]
        self.assertEqual(values, sorted(values))
        self.assertIn(("3D 分类推理中", 40), events)
        self.assertIn(("3D 分类推理中", 43), events)
        self.assertIn(("3D 分割推理中", 71), events)
        self.assertIn(("分割结果后处理", 98), events)
        self.assertIn(("正在生成影像预览", 99), events)
        self.assertLess(max(values), 100)

    def test_segmentation_service_reports_stages_without_exposing_device(self):
        stages, fractions = [], []
        def predict(subject, **options):
            options["stage_callback"]("读取四模态影像")
            options["stage_callback"]("3D 分割推理中")
            options["progress_callback"](0.5)
            options["stage_callback"]("保存分割结果")
            return {"device": "cpu", "model": {}, "spatial": {}, "labels": {}, "regions": {},
                    "saved_path": "synthetic.nii.gz", "timing": {}}
        with (
            TemporaryDirectory() as directory,
            patch.object(inference_service, "_load_3d_segmentation_namespace", return_value={"torch": torch, "predict": predict}),
            patch.object(inference_service, "resolve_device", return_value=torch.device("cpu")),
            patch.object(inference_service, "_load_3d_segmentation_model", return_value=object()),
        ):
            inference_service.segment_volume({}, Path(directory), progress_callback=fractions.append, stage_callback=stages.append)
        self.assertEqual(fractions, [0.5])
        self.assertEqual(stages, ["加载分割模型", "读取四模态影像", "3D 分割推理中", "保存分割结果"])

    def test_segmentation_predict_reports_preprocessing_and_postprocessing_steps(self):
        import nibabel as nib
        import numpy as np
        from models.segmentation3d import inference

        images = np.arange(1, 257, dtype=np.float32).reshape((4, 4, 4, 4))
        reference = nib.Nifti1Image(np.zeros((4, 4, 4), dtype=np.float32), np.eye(4))
        stages = []
        with (
            TemporaryDirectory() as directory,
            patch.object(inference, "_configure_inference_runtime"),
            patch.object(inference, "_load_and_validate_subject", return_value=(images, reference, {m: Path(f"synthetic-{m}.nii.gz") for m in inference.MODALITIES})),
            patch.object(inference, "_run_full_volume_inference", return_value=np.zeros((4, 4, 4), dtype=np.uint8)),
        ):
            inference.predict({}, device="cpu", model=Mock(), save_nifti=Path(directory) / "synthetic.nii.gz",
                              stage_callback=stages.append)
        self.assertEqual(stages, ["读取四模态影像", "分割影像归一化", "3D 分割推理中", "分割结果后处理", "保存分割结果"])


class NaturalProgressTests(unittest.TestCase):
    read_progress = LegacyProgressTests.read_progress

    def test_three_second_polling_reduces_a_large_jump_without_exceeding_actual_work(self):
        metadata = {"progress": 71, "progress_stage": "3D 分割推理中",
                    "progress_display_from": 44, "progress_display_started_at": 100.0,
                    "progress_display_duration": 6.0}
        observed = []
        for now in (100.0, 103.0, 106.0):
            with patch("services.inference_progress.time", return_value=now):
                observed.append(self.read_progress(metadata)["progress"])
        self.assertEqual(observed, [44, 57, 71])
        self.assertLessEqual(max(b - a for a, b in zip([44] + observed, observed)), 14)
        self.assertTrue(all(value <= metadata["progress"] for value in observed))

    def test_new_work_sample_starts_from_current_display_without_moving_backwards(self):
        from services.inference_progress import displayed_progress
        job = SimpleNamespace(id="natural-progress", meta={}, save_meta=Mock())
        with patch("workers.inference_jobs.time", side_effect=[90.0, 100.0, 103.0]):
            inference_jobs._record_job_progress(job, "fixture", "3D 分割推理中", 44)
            inference_jobs._record_job_progress(job, "fixture", "3D 分割推理中", 71)
            before = displayed_progress(job.meta, 71, now=103.0)
            inference_jobs._record_job_progress(job, "fixture", "3D 分割推理中", 80)
        self.assertEqual(before, 57)
        self.assertEqual(displayed_progress(job.meta, 80, now=103.0), before)
        self.assertEqual(displayed_progress(job.meta, 80, now=106.0), 80)

    def test_phase_transitions_keep_legacy_44_and_99_boundaries(self):
        from services.inference_progress import displayed_progress
        job = SimpleNamespace(id="phase-progress", meta={}, save_meta=Mock())
        for value in (36, 43, 44, 98, 99):
            with patch("workers.inference_jobs.time", return_value=100.0):
                inference_jobs._record_job_progress(job, "fixture", "真实阶段", value)
            if value in (44, 99):
                self.assertEqual(displayed_progress(job.meta, value, now=100.0), value)

    def test_initial_running_progress_gradually_catches_up_from_zero(self):
        from services.inference_progress import displayed_progress
        job = SimpleNamespace(id="initial-progress", meta={}, save_meta=Mock())
        with patch("workers.inference_jobs.time", return_value=100.0):
            inference_jobs._record_job_progress(job, "fixture", "分类影像预处理", 36)
        self.assertEqual([displayed_progress(job.meta, 36, now=t) for t in (100, 103, 106)], [0, 18, 36])
        self.assertEqual(self.read_progress({})["progress"], 0)

    def test_small_completed_work_increments_are_not_delayed(self):
        from services.inference_progress import displayed_progress
        for target in (45, 46):
            with self.subTest(target=target):
                job = SimpleNamespace(id="small-progress", meta={}, save_meta=Mock())
                with patch("workers.inference_jobs.time", side_effect=[100.0, 101.0]):
                    inference_jobs._record_job_progress(job, "fixture", "分割", 44)
                    inference_jobs._record_job_progress(job, "fixture", "分割", target)
                self.assertEqual(displayed_progress(job.meta, target, now=101.0), target)

    def test_transition_duration_uses_observed_progress_interval_with_a_short_cap(self):
        for interval, expected in ((0.1, 3.0), (4.0, 4.0), (60.0, 6.0)):
            with self.subTest(interval=interval):
                job = SimpleNamespace(id="interval-progress", meta={}, save_meta=Mock())
                with patch("workers.inference_jobs.time", side_effect=[100.0, 100.0 + interval]):
                    inference_jobs._record_job_progress(job, "fixture", "分割", 44)
                    inference_jobs._record_job_progress(job, "fixture", "分割", 50)
                self.assertEqual(job.meta["progress_display_duration"], expected)

    def test_invalid_transition_metadata_falls_back_to_confirmed_progress(self):
        from services.inference_progress import displayed_progress
        for key, value in (("progress_display_from", float("nan")),
                           ("progress_display_from", 20),
                           ("progress_display_duration", 1000),
                           ("progress_display_duration", 0),
                           ("progress_display_started_at", None)):
            with self.subTest(key=key, value=value):
                metadata = {"progress_display_from": 44, "progress_display_started_at": 100.0,
                            "progress_display_duration": 6.0, key: value}
                self.assertEqual(displayed_progress(metadata, 71, now=103.0), 71)


class LegacyHttpProgressTests(unittest.TestCase):
    def test_legacy_get_task_receives_same_fields_and_terminal_state(self):
        from fastapi.testclient import TestClient
        from api.app import app
        from api.auth import get_current_user
        from core.user_records import UserRecord

        now = datetime.now(timezone.utc)
        user = UserRecord(user_id="progress-user", username="progress-user", hashed_password="unused",
                          created_at=now, updated_at=now)
        previous = app.dependency_overrides.get(get_current_user)
        app.dependency_overrides[get_current_user] = lambda: user
        try:
            with TemporaryDirectory() as directory:
                record = task_record()
                metadata = {"progress": 50, "progress_stage": "3D 分割推理中", "progress_stage_started_at": 100.0}
                with (
                    patch("api.routes.tasks.require_task_dir", return_value=Path(directory)),
                    patch("api.routes.tasks.task_repository.load_for_user", return_value=record),
                    patch("api.routes.tasks.reconcile_task_job", return_value=record),
                    patch("services.task_queue.get_redis_client", return_value=Mock()),
                    patch("services.task_queue.Job.fetch", return_value=SimpleNamespace(meta=metadata)),
                    patch("services.inference_progress.time", return_value=110.0),
                    TestClient(app) as client,
                ):
                    response = client.get("/tasks/progress-fixture")
                    self.assertEqual(response.status_code, 200)
                    payload = response.json()
                    self.assertEqual(payload["progress"], 50)
                    self.assertNotIn("CPU", payload["progress_stage"])
                    self.assertNotIn("GPU", payload["progress_stage"])
                    self.assertIn("10秒", payload["progress_stage"])
                    self.assertEqual(payload["status"], "running")
                    record.status = TaskStatus.SUCCEEDED
                    completed = client.get("/tasks/progress-fixture").json()
                    self.assertEqual(completed["status"], "succeeded")
                    self.assertIsNone(completed["progress"])
        finally:
            if previous is None:
                app.dependency_overrides.pop(get_current_user, None)
            else:
                app.dependency_overrides[get_current_user] = previous


if __name__ == "__main__":
    unittest.main()
