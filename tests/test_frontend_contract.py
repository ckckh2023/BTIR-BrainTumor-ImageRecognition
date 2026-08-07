'''前端任务操作与 3D 结果展示的轻量契约回归测试'''

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_HTML = PROJECT_ROOT / "frontend" / "index.html"


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = FRONTEND_HTML.read_text(encoding="utf-8")
        cls.detail_html = (
            PROJECT_ROOT / "frontend" / "components" / "btir-detail-table.js"
        ).read_text(encoding="utf-8")
        cls.toast_html = (
            PROJECT_ROOT / "frontend" / "components" / "btir-toast.js"
        ).read_text(encoding="utf-8")
        cls.login_html = (
            PROJECT_ROOT / "frontend" / "login.html"
        ).read_text(encoding="utf-8")
        cls.viewer_html = (
            PROJECT_ROOT / "frontend" / "volume_viewer.js"
        ).read_text(encoding="utf-8")

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
        self.assertIn("分类与分割一致性", self.html)
        self.assertIn("V1 终盲测试集整体正确率 95.0%", self.html)
        self.assertIn("AI 分析结论", self.html)

    def test_result_panel_keeps_overview_separate_from_details(self) -> None:
        self.assertIn('class="result-overview"', self.html)
        self.assertIn('class="result-details"', self.html)
        self.assertIn("查看详细数据", self.html)
        self.assertIn("模型观察", self.html)
        self.assertIn("提示肿瘤相关异常", self.html)

    def test_left_panel_keeps_expanded_upload_and_result_in_scroll_area(self) -> None:
        self.assertIn(".left-panel", self.html)
        self.assertIn("overflow-y: auto;", self.html)
        self.assertIn(".result-section", self.html)
        self.assertIn("min-height: 280px;", self.html)
        self.assertIn("max-height: 420px;", self.html)

    def test_upload_flow_supports_dicom_folder_conversion(self) -> None:
        self.assertIn("DICOM 病例文件夹", self.html)
        self.assertIn("volumeDicomFiles", self.html)
        self.assertIn("selectDicomFiles", self.html)
        self.assertIn("triggerVolumeCaseFolderPicker", self.html)
        self.assertIn("onVolumeFolderSelected", self.html)
        self.assertIn("/tasks/3d/dicom", self.html)
        self.assertIn("未发现明显异常", self.html)

    def test_dicom_duplicate_series_requires_user_selection(self) -> None:
        self.assertIn("dicom_series_selection_required", self.html)
        self.assertIn("dicomSeriesCandidates", self.html)
        self.assertIn("dicomSeriesSelections", self.html)
        self.assertIn("请选择用于分析的 DICOM 序列", self.html)
        self.assertIn('<template v-for="modality in volumeModalities"', self.html)
        self.assertIn("正在上传 ", self.html)

    def test_upload_phase_is_included_in_inference_progress(self) -> None:
        self.assertIn("uploadTaskFiles", self.html)
        self.assertIn("xhr.upload.onprogress", self.html)
        self.assertIn("正在上传数据", self.html)
        self.assertIn("正在压缩/上传数据", self.html)

    def test_volume_upload_starts_with_drop_zone_and_recovers_from_ambiguity(self) -> None:
        self.assertIn("拖入 NIfTI 或 DICOM 病例文件夹，或 ZIP 压缩包", self.html)

    def test_async_run_shows_the_backend_error_detail(self) -> None:
        self.assertIn(
            "await this.responseError(runResponse, '运行模型')",
            self.html,
        )
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
        self.assertIn("volumeArchiveFile || volumeDicomFiles.length", self.html)
        self.assertIn("selectedVolumeFiles", self.html)
        self.assertIn("clearVolumeUpload", self.html)
        self.assertIn("删除已选文件", self.html)

    def test_volume_upload_offers_manual_per_modality_picking(self) -> None:
        self.assertIn("手动上传四个 NIfTI 文件", self.html)
        self.assertIn("triggerVolumeManualPicker", self.html)
        self.assertIn("volumeManualMode", self.html)
        self.assertIn("volumeSourceSummary", self.html)

    def test_upload_controls_collapse_during_and_after_an_active_task(self) -> None:
        self.assertIn('v-if="!loading && !taskId"', self.html)
        self.assertIn('v-if="taskId && !loading"', self.html)
        self.assertIn("重新上传病例", self.html)
        self.assertIn("startNewUpload()", self.html)
        self.assertIn("this.volumeDicomFiles = []", self.html)

    def test_result_integrated_view_flattens_json_key_value_pairs(self) -> None:
        self.assertIn("详细结果", self.html)
        self.assertIn("type: 'integrated'", self.html)
        self.assertIn("md-table-viewer", self.html)
        self.assertNotIn("md-table-title", self.html)
        self.assertNotIn("md-table-th-key", self.html)
        self.assertNotIn("键</th>", self.html)
        self.assertNotIn("# {{ section.label }}", self.html)
        self.assertNotIn('class="copy-btn"', self.html)
        self.assertIn("label: 'frontend_result.json', path: rf.frontend", self.html)
        self.assertNotIn("classification.json', 'classification'", self.html)
        self.assertNotIn("segmentation.json', 'segmentation'", self.html)
        self.assertIn("flattenKeyValuePairs", self.detail_html)
        self.assertIn("visibleRows(section)", self.detail_html)
        self.assertIn("toggleRow(row)", self.detail_html)
        self.assertIn("collapsed: Boolean(hasChildren)", self.detail_html)
        self.assertIn("md-table-copy", self.detail_html)
        self.assertIn('@click="copyDetail"', self.detail_html)
        self.assertIn("rowCount", self.detail_html)
        self.assertIn("md-table-toggle", self.html)

    def test_detail_table_and_toast_are_extracted_components(self) -> None:
        self.assertIn("components/btir-detail-table.js", self.html)
        self.assertIn("components/btir-toast.js", self.html)
        self.assertIn("<btir-detail-table", self.html)
        self.assertIn("<btir-toast></btir-toast>", self.html)
        self.assertIn("registry['btir-detail-table']", self.detail_html)
        self.assertIn("registry['btir-toast']", self.toast_html)
        self.assertIn("btirApp.component(name", self.html)
        self.assertIn("btir:toast", self.toast_html)

    def test_login_page_synced_with_design_tokens(self) -> None:
        self.assertIn("--btir-primary:", self.login_html)
        self.assertIn('[data-theme="dark"]', self.login_html)
        self.assertIn("theme-toggle", self.login_html)
        self.assertIn("toggleTheme", self.login_html)
        self.assertIn(".tab:hover:not(.active)", self.login_html)
        self.assertIn("input:hover", self.login_html)
        self.assertIn("submit-btn:hover:not(:disabled)", self.login_html)
        self.assertNotIn("linear-gradient(180deg, #1a3a6b", self.login_html)

    def test_json_raw_tabs_removed_and_3d_viewer_stays_default(self) -> None:
        self.assertNotIn("addFile('frontend_result.json'", self.html)
        self.assertNotIn("addFile('classification.json'", self.html)
        self.assertNotIn("addFile('segmentation.json'", self.html)
        self.assertLess(
            self.html.index("label: '3D查看'"),
            self.html.index("label: '详细结果'"),
        )

    def test_modern_ui_tokens_toast_skeleton_and_visualization(self) -> None:
        self.assertIn("--btir-primary:", self.html)
        self.assertIn("app-toast", self.html)
        self.assertIn("showToastMessage", self.html)
        self.assertIn("task-skeleton", self.html)
        self.assertIn("skeleton-shimmer", self.html)
        self.assertIn("result-ring", self.html)
        self.assertIn("result-chart-line", self.html)
        self.assertIn("regionBarWidth", self.html)
        self.assertIn("probabilityPoints", self.html)
        self.assertIn('class="icon"', self.html)

    def test_logo_uses_theme_mask_without_frame(self) -> None:
        self.assertIn("mask: url('/assets/icon_exp.png')", self.html)
        self.assertIn('[data-theme="dark"] .app-logo', self.html)
        self.assertIn('class="app-logo"', self.html)
        self.assertNotIn("border-radius: 12px", self.html)

    def test_topbar_actions_are_embedded_icon_buttons(self) -> None:
        self.assertNotIn(">登出</button>", self.html)
        self.assertNotIn("四模态脑肿瘤 MRI 智能分析平台", self.html)
        self.assertIn('title="退出登录"', self.html)
        self.assertIn('aria-label="退出登录"', self.html)
        self.assertIn(".logout-btn:hover", self.html)
        self.assertIn("border-radius: 50%", self.html)

    def test_segmentation_judgment_uses_ring_and_legend(self) -> None:
        self.assertIn("result-ring-value seg", self.html)
        self.assertIn("segRingDashOffset", self.html)
        self.assertIn("segPercent", self.html)
        self.assertIn("segTotalVolume", self.html)
        self.assertIn("result-seg-legend", self.html)
        self.assertIn("result-seg-dot", self.html)

    def test_task_flow_optimizations(self) -> None:
        self.assertNotIn("this.taskListMode = 'archived'", self.html)
        self.assertNotIn("✓ 3D分析完成", self.html)
        self.assertIn(
            "statusText || analysisProgress || (analysisPolling && taskId && !analysisCancelled)",
            self.html,
        )

    def test_niivue_preload_warms_3d_viewer(self) -> None:
        self.assertIn(
            '<link rel="preload" href="./vendor/niivue.umd.js" as="script">',
            self.html,
        )
        self.assertIn("window.BtirVolumeViewer?.preload?.()", self.html)
        self.assertIn("global.BtirVolumeViewer.preload = preloadNiiVue", self.viewer_html)
        self.assertIn("function preloadNiiVue", self.viewer_html)

    def test_probability_chart_nodes_show_hover_values(self) -> None:
        self.assertIn("chartPoints", self.html)
        self.assertIn("result-chart-node", self.html)
        self.assertIn("showChartPoint", self.html)
        self.assertIn("result-chart-tooltip", self.html)
        self.assertIn("probabilityText", self.html)
        self.assertIn("chartHoverVisible", self.html)
        self.assertIn("transition: opacity 0.45s ease", self.html)

    def test_scroll_reveal_and_chart_draw_animations(self) -> None:
        self.assertIn("[data-reveal]", self.html)
        self.assertIn("initRevealObserver", self.html)
        self.assertIn("IntersectionObserver", self.html)
        self.assertIn("ringDisplayOffset", self.html)
        self.assertIn("segRingDisplayOffset", self.html)
        self.assertIn("probLineLength", self.html)
        self.assertIn("probLineDrawn", self.html)
        self.assertIn("animationDelay", self.html)
        self.assertIn("animation: fade-in 0.2s ease", self.html)

    def test_detail_table_translates_json_keys_to_chinese(self) -> None:
        self.assertIn("KEY_LABELS", self.detail_html)
        self.assertIn("translateKey", self.detail_html)
        self.assertIn("rawKey", self.detail_html)
        self.assertIn("分类结果", self.detail_html)
        self.assertIn("协议版本", self.detail_html)
        self.assertIn("置信度", self.detail_html)


if __name__ == "__main__":
    unittest.main()
