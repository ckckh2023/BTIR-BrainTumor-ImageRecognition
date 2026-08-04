'''前端任务操作与 3D 结果展示的轻量契约回归测试'''

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_HTML = PROJECT_ROOT / "frontend" / "index.html"


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = FRONTEND_HTML.read_text(encoding="utf-8")

    def test_3d_result_does_not_render_an_outdated_hint(self) -> None:
        self.assertNotIn("当前 3D 路线仅提供分割与定量统计", self.html)
        self.assertNotIn('class="result-note"', self.html)

    def test_upload_flow_is_3d_only(self) -> None:
        self.assertIn("/tasks/3d", self.html)
        self.assertNotIn("analysisMode", self.html)
        self.assertNotIn("switchAnalysisMode", self.html)
        self.assertNotIn("image-viewer", self.html)
        self.assertNotIn(".jpg", self.html)

    def test_active_task_polling_is_fast_then_backs_off(self) -> None:
        self.assertIn("pollingStartedAt", self.html)
        self.assertIn("elapsedPollingMs", self.html)
        self.assertIn("elapsedPollingMs < 15_000", self.html)
        self.assertIn("elapsedPollingMs < 60_000 ? 1500 : 3000", self.html)

    def test_task_manager_exposes_cancel_action(self) -> None:
        self.assertIn("canCancelTask(task.status)", self.html)
        self.assertIn("@click=\"cancelTask(task)\"", self.html)
        self.assertIn("/${encodeURIComponent(task.task_id)}/cancel`", self.html)

    def test_task_manager_exposes_run_history(self) -> None:
        self.assertIn("@click=\"toggleTaskRunHistory(task)\"", self.html)
        self.assertIn("/${encodeURIComponent(taskId)}/runs?limit=20&offset=0`", self.html)
        self.assertIn("formatInferenceTime(run.inference_ms)", self.html)
        self.assertIn("value === null || value === undefined", self.html)

    def test_volume_viewer_exposes_download_progress(self) -> None:
        self.assertIn("volumeDownload", self.html)
        self.assertIn("volumeDownloadPercent", self.html)
        self.assertIn("onProgress", self.html)
        self.assertIn("volume-download-track", self.html)

    def test_upload_gzips_nifti_in_browser_when_supported(self) -> None:
        self.assertIn("CompressionStream('gzip')", self.html)
        self.assertIn("gzipVolumeFileForUpload", self.html)
        self.assertIn("正在压缩", self.html)
        self.assertIn("`${file.name}.gz`", self.html)

    def test_result_file_tabs_keep_json_and_volume_only(self) -> None:
        self.assertNotIn("下载3D掩码", self.html)
        self.assertNotIn("`下载 ${modality.label}`", self.html)
        self.assertIn("downloadFiles", self.html)
        self.assertIn("file-download-link", self.html)
        self.assertNotIn("addDownload('classification.json'", self.html)
        self.assertNotIn("addDownload('segmentation.json'", self.html)
        self.assertNotIn("addDownload('frontend_result.json'", self.html)
        self.assertNotIn("output/${taskId}/frontend_result.json", self.html)

    def test_running_analysis_exposes_cancel_button(self) -> None:
        self.assertIn("cancelCurrentAnalysis", self.html)
        self.assertIn("cancel-analysis-btn", self.html)
        self.assertIn("analysisCancelled", self.html)
        self.assertIn("analysisPolling", self.html)
        self.assertIn("已取消任务", self.html)

    def test_running_analysis_exposes_inference_progress(self) -> None:
        self.assertIn("analysisProgress", self.html)
        self.assertIn("analysis-progress-track", self.html)
        self.assertIn("analysisProgressPercent", self.html)
        self.assertIn("resultData.progress_stage", self.html)

    def test_supplementary_analysis_is_rendered_as_escaped_text(self) -> None:
        self.assertIn("supplementaryAnalysis", self.html)
        self.assertIn("supplementary_analysis", self.html)
        self.assertIn("analysisConsistencyLabel", self.html)
        self.assertIn("分析模型：", self.html)
        self.assertIn("supplementaryRecommendation(supplementaryAnalysis)", self.html)
        self.assertIn("supplementaryRecommendation(analysis)", self.html)
        self.assertIn("result-analysis-provider", self.html)
        self.assertNotIn("v-html=\"supplementaryAnalysis", self.html)

    def test_frontend_renders_local_segmentation_first_consensus(self) -> None:
        self.assertIn("modelConsensus", self.html)
        self.assertIn("综合识别结论", self.html)
        self.assertIn("AI 分析结论", self.html)

    def test_result_panel_keeps_overview_separate_from_details(self) -> None:
        self.assertIn('class="result-overview"', self.html)
        self.assertIn('class="result-details"', self.html)
        self.assertIn("查看详细数据", self.html)
        self.assertIn("模型观察", self.html)
        self.assertIn("提示肿瘤相关异常", self.html)
        self.assertIn("未发现明显异常", self.html)

    def test_upload_phase_is_included_in_inference_progress(self) -> None:
        self.assertIn("uploadTaskFiles", self.html)
        self.assertIn("xhr.upload.onprogress", self.html)
        self.assertIn("正在上传数据", self.html)
        self.assertIn("正在压缩/上传数据", self.html)

    def test_volume_upload_starts_with_drop_zone_and_recovers_from_ambiguity(self) -> None:
        self.assertIn("拖入一个病例文件夹或 ZIP 压缩包", self.html)
        self.assertIn("onVolumeDrop", self.html)
        self.assertIn("showVolumeCorrection", self.html)
        self.assertIn("archive_modality_selection_required", self.html)
        self.assertIn("请选择生效文件", self.html)
        self.assertIn("/tasks/3d/archive", self.html)
        self.assertIn("volumeCorrectionVisible", self.html)
        self.assertIn("this.volumeCorrectionVisible = false", self.html)
        self.assertIn("volumeSourceMenuVisible", self.html)
        self.assertIn("triggerVolumeArchivePicker", self.html)
        self.assertIn("无法读取拖入内容", self.html)

    def test_selected_folder_and_archive_can_be_reviewed_and_cleared(self) -> None:
        self.assertIn("已选择文件夹", self.html)
        self.assertIn("selectedVolumeFiles", self.html)
        self.assertIn("clearVolumeUpload", self.html)
        self.assertIn("删除已选压缩包", self.html)

    def test_upload_controls_collapse_during_and_after_an_active_task(self) -> None:
        self.assertIn('v-if="!loading && !taskId"', self.html)
        self.assertIn('v-else-if="taskId && !loading"', self.html)
        self.assertIn("重新上传病例", self.html)
        self.assertIn("startNewUpload()", self.html)


if __name__ == "__main__":
    unittest.main()
