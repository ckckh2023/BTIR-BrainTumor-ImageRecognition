'''前端任务操作与 3D 结果展示的轻量契约回归测试'''

import json
from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_HTML = PROJECT_ROOT / "frontend" / "index.html"


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = FRONTEND_HTML.read_text(encoding="utf-8")
        cls.theme_css = (
            PROJECT_ROOT / "frontend" / "theme.css"
        ).read_text(encoding="utf-8")
        cls.app_css = (
            PROJECT_ROOT / "frontend" / "app.css"
        ).read_text(encoding="utf-8")
        cls.app_js = (
            PROJECT_ROOT / "frontend" / "app.js"
        ).read_text(encoding="utf-8")
        cls.detail_html = (
            PROJECT_ROOT / "frontend" / "components" / "btir-detail-table.js"
        ).read_text(encoding="utf-8")
        cls.toast_html = (
            PROJECT_ROOT / "frontend" / "components" / "btir-toast.js"
        ).read_text(encoding="utf-8")
        cls.login_html = (
            PROJECT_ROOT / "frontend" / "login.html"
        ).read_text(encoding="utf-8")
        cls.auth_css = (
            PROJECT_ROOT / "frontend" / "auth.css"
        ).read_text(encoding="utf-8")
        cls.change_password_html = (
            PROJECT_ROOT / "frontend" / "change-password.html"
        ).read_text(encoding="utf-8")
        cls.viewer_html = (
            PROJECT_ROOT / "frontend" / "volume_viewer.js"
        ).read_text(encoding="utf-8")
        cls.guide_html = (
            PROJECT_ROOT / "frontend" / "guide.html"
        ).read_text(encoding="utf-8")

    def test_3d_result_does_not_render_an_outdated_hint(self) -> None:
        self.assertNotIn("当前 3D 路线仅提供分割与定量统计", self.html)
        self.assertNotIn('class="result-note"', self.html)

    def test_upload_flow_is_3d_only(self) -> None:
        self.assertIn("/tasks/3d", self.app_js)
        self.assertNotIn("analysisMode", self.html)
        self.assertNotIn("switchAnalysisMode", self.html)
        self.assertNotIn("image-viewer", self.html)
        self.assertNotIn(".jpg", self.html)

    def test_active_task_polling_is_fast_then_backs_off(self) -> None:
        self.assertIn("pollingStartedAt", self.app_js)
        self.assertIn("elapsedPollingMs", self.app_js)
        self.assertIn("elapsedPollingMs < 15_000", self.app_js)
        self.assertIn("elapsedPollingMs < 60_000 ? 1500 : 3000", self.app_js)

    def test_task_manager_exposes_cancel_action(self) -> None:
        self.assertIn("canCancelTask(task.status)", self.html)
        self.assertIn("@click=\"cancelTask(task)\"", self.html)
        self.assertIn("/${encodeURIComponent(task.task_id)}/cancel`", self.app_js)

    def test_task_manager_exposes_run_history(self) -> None:
        self.assertIn("@click=\"toggleTaskRunHistory(task)\"", self.html)
        self.assertIn("/${encodeURIComponent(taskId)}/runs?limit=20&offset=0`", self.app_js)
        self.assertIn("formatInferenceTime(run.inference_ms)", self.html)
        self.assertIn("value === null || value === undefined", self.app_js)

    def test_volume_viewer_exposes_download_progress(self) -> None:
        self.assertIn("volumeDownload", self.html)
        self.assertIn("volumeDownloadPercent", self.html)
        self.assertIn("onProgress", self.app_js)
        self.assertIn("volume-download-track", self.html)

    def test_upload_gzips_nifti_in_browser_when_supported(self) -> None:
        self.assertIn("CompressionStream('gzip')", self.app_js)
        self.assertIn("gzipVolumeFileForUpload", self.app_js)
        self.assertIn("正在压缩", self.app_js)
        self.assertIn("`${file.name}.gz`", self.app_js)

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
        self.assertIn("已取消任务", self.app_js)

    def test_running_analysis_exposes_inference_progress(self) -> None:
        self.assertIn("analysisProgress", self.html)
        self.assertIn("analysis-progress-track", self.html)
        self.assertIn("displayProgress", self.html)
        self.assertIn("resultData.progress_stage", self.app_js)

    def test_progress_bar_smooth_and_balanced_phases(self) -> None:
        self.assertIn("mappedProgressPercent", self.app_js)
        self.assertIn("startProgressMotion", self.app_js)
        self.assertIn("progressPhaseCeiling", self.app_js)
        self.assertIn("progressMotionActive: false", self.app_js)
        self.assertIn("displayProgress: 0", self.app_js)
        self.assertIn("mapped = 30 + ((raw - 36) / 8) * 25", self.app_js)
        self.assertIn("mapped = 55 + ((raw - 44) / 54) * 35", self.app_js)
        self.assertIn("mapped = 90 + ((raw - 98) / 2) * 10", self.app_js)
        self.assertIn("analysis-progress-seg", self.html)
        self.assertIn("analysis-progress-shimmer", self.app_css)

    def test_result_settle_animates_to_100_then_fades(self) -> None:
        self.assertIn("settleAndPresentResult", self.app_js)
        self.assertIn("percent: 100", self.app_js)
        self.assertIn("分析完成，正在呈现结果...", self.app_js)
        self.assertIn('<transition name="status-fade">', self.html)
        self.assertIn("status-fade-leave-active", self.app_css)

    def test_analysis_phases_show_classification_regardless_of_poll_timing(self) -> None:
        self.assertIn("analysisPhases", self.app_js)
        self.assertIn("reached(44)", self.app_js)
        self.assertIn("3D 分类", self.app_js)
        self.assertIn("3D 分割", self.app_js)
        self.assertIn("综合分析", self.app_js)
        self.assertIn('v-if="analysisPhases.length"', self.html)
        self.assertIn("analysis-phase", self.app_css)

    def test_supplementary_analysis_is_rendered_as_escaped_text(self) -> None:
        self.assertIn("supplementaryAnalysis", self.html)
        self.assertIn("supplementary_analysis", self.app_js)
        self.assertIn("AI 辅助分析", self.html)
        self.assertIn("提供方", self.detail_html)
        self.assertNotIn("v-html=\"supplementaryAnalysis", self.html)

    def test_frontend_renders_dual_model_summary_before_details(self) -> None:
        self.assertIn("modelConsensus", self.html)
        self.assertIn("consensusCard", self.app_js)
        self.assertIn('data-testid="dual-model-summary"', self.html)
        self.assertIn("综合结果", self.html)
        self.assertIn("分类提示", self.html)
        self.assertIn("分割结果", self.html)
        self.assertIn("case-summary-card", self.app_css)
        self.assertIn("两模型结果相互支持", self.app_js)
        self.assertIn("AI 辅助分析", self.html)

    def test_model_metrics_are_loaded_from_metrics_file(self) -> None:
        metrics_file = PROJECT_ROOT / "assets" / "metrics.json"
        self.assertTrue(metrics_file.is_file())
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))
        self.assertEqual(metrics["total"], metrics["correct"])
        self.assertGreaterEqual(metrics["total"], 1)
        self.assertIn("modelMetrics", self.html)
        self.assertIn("modelMetrics: null", self.app_js)
        self.assertIn("/assets/metrics.json", self.app_js)
        self.assertIn("样例核对：{{ modelMetrics.correct }}/{{ modelMetrics.total }}", self.html)
        self.assertIn("样例核对：3/3 例 BraTS19 测试病例分类结果与预期一致", self.html)
        self.assertIn("result-metrics-row", self.app_css)
        self.assertNotIn("95.0%", self.html)

    def test_result_panel_keeps_overview_separate_from_details(self) -> None:
        self.assertIn("analysis-summary", self.html)
        self.assertIn("AI 辅助分析", self.html)
        self.assertIn("提示肿瘤相关异常", self.html)
        self.assertIn("影像与模型依据", self.html)
        self.assertIn("最大病灶层", self.html)
        self.assertIn("查看详细数据", self.html)
        self.assertIn("casePreviewUrl", self.app_js)
        self.assertIn("loadCasePreview", self.app_js)

    def test_left_panel_keeps_expanded_upload_and_result_in_scroll_area(self) -> None:
        self.assertIn(".left-panel", self.app_css)
        self.assertIn(".left-panel-scroll", self.app_css)
        self.assertIn("overflow-y: auto;", self.app_css)
        self.assertIn(".result-section", self.app_css)
        self.assertIn("flex: 1 1 auto;", self.app_css)
        self.assertIn("min-height: 280px;", self.app_css)

    def test_completed_case_uses_the_full_result_workspace(self) -> None:
        self.assertIn("result-workspace", self.html)
        self.assertIn("isResultWorkspace", self.app_js)
        self.assertIn("重新上传病例", self.html)
        self.assertIn(".result-workspace .left-panel", self.app_css)
        self.assertIn(".result-workspace .case-overview", self.app_css)
        self.assertIn("app-main-nav", self.html)
        self.assertIn("病例分析", self.html)
        self.assertIn("任务管理", self.html)
        self.assertIn("activeRightView === 'tasks'", self.app_js)
        self.assertIn("topbar-reupload-btn", self.html)
        self.assertNotIn("right-header", self.html)
        self.assertIn('v-if="taskId && !loading"', self.html)

    def test_brand_area_returns_to_the_upload_page(self) -> None:
        self.assertIn("app-home-btn", self.html)
        self.assertIn('@click.prevent="startNewUpload()"', self.html)
        self.assertIn(".app-home-btn", self.app_css)

    def test_refresh_restores_the_current_workspace(self) -> None:
        self.assertIn("persistWorkspaceState", self.app_js)
        self.assertIn("restoreWorkspaceState", self.app_js)
        self.assertIn("localStorage.getItem('btir_workspace')", self.app_js)
        self.assertIn("sessionStorage.getItem('btir_workspace')", self.app_js)
        self.assertIn("url.searchParams.set('task', this.taskId)", self.app_js)
        self.assertIn("workspaceRestoring", self.app_js)
        self.assertIn('v-show="!workspaceRestoring"', self.html)
        self.assertIn("await this.restoreWorkspaceState()", self.app_js)
        self.assertIn("taskId: this.taskId || ''", self.app_js)
        self.assertIn("savedWorkspace.view === 'tasks'", self.app_js)

    def test_empty_right_panel_is_not_rendered_during_upload(self) -> None:
        self.assertIn("hasRightPanel", self.app_js)
        self.assertIn('class="right-panel" v-if="hasRightPanel"', self.html)
        self.assertIn("single-pane-workspace", self.html)
        self.assertIn(".single-pane-workspace .left-panel", self.app_css)

    def test_upload_action_and_task_pagination_are_centered(self) -> None:
        self.assertIn("upload-action", self.html)
        self.assertIn("place-items: center;", self.app_css)
        self.assertIn(".task-pagination", self.app_css)
        self.assertIn("justify-content: center;", self.app_css)

    def test_task_manager_marks_the_current_task(self) -> None:
        self.assertIn("task.task_id === taskId", self.html)
        self.assertIn("task-current-badge", self.html)
        self.assertIn(".task-card.current", self.app_css)

    def test_active_task_card_opens_its_result(self) -> None:
        self.assertIn("viewTaskResult(task)", self.html)
        self.assertIn("task-card-actions\" @click.stop", self.html)
        self.assertIn(".task-card.clickable", self.app_css)
        self.assertIn("查看结果", self.html)
        self.assertIn("task-small-btn primary", self.html)

    def test_upload_flow_supports_dicom_folder_conversion(self) -> None:
        self.assertIn("DICOM 病例文件夹", self.html)
        self.assertIn("volumeDicomFiles", self.html)
        self.assertIn("selectDicomFiles", self.app_js)
        self.assertIn("triggerVolumeCaseFolderPicker", self.html)
        self.assertIn("onVolumeFolderSelected", self.html)
        self.assertIn("/tasks/3d/dicom", self.app_js)
        self.assertIn("未发现明显异常", self.html)

    def test_dicom_duplicate_series_requires_user_selection(self) -> None:
        self.assertIn("dicom_series_selection_required", self.app_js)
        self.assertIn("dicomSeriesCandidates", self.html)
        self.assertIn("dicomSeriesSelections", self.html)
        self.assertIn("请选择用于分析的 DICOM 序列", self.html)
        self.assertIn('<template v-for="modality in volumeModalities"', self.html)
        self.assertIn("正在上传 ", self.app_js)

    def test_upload_phase_is_included_in_inference_progress(self) -> None:
        self.assertIn("uploadTaskFiles", self.app_js)
        self.assertIn("xhr.upload.onprogress", self.app_js)
        self.assertIn("正在上传数据", self.app_js)
        self.assertIn("正在压缩/上传数据", self.app_js)

    def test_result_status_visible_during_upload_before_task_id(self) -> None:
        self.assertIn('class="result-section"', self.html)
        self.assertIn("v-if=\"taskId || analysisActive\"", self.html)
        self.assertIn("analysis-pending", self.html)
        self.assertIn("searchTasks", self.app_js)
        self.assertNotIn("@input=\"scheduleTaskSearch\"", self.html)
        self.assertNotIn("@change=\"scheduleTaskSearch(true)\"", self.html)
        self.assertIn("workspaceRestoring", self.html)
        self.assertIn("analysisActive: false", self.app_js)
        self.assertIn("this.analysisActive = true", self.app_js)
        self.assertIn("this.analysisActive = false", self.app_js)
        self.assertIn("topbar-github-link", self.html)
        self.assertIn("https://github.com/ckckh2023/BTIR-BrainTumor-ImageRecognition", self.html)
        self.assertIn('M8 0C3.58 0 0 3.58 0 8', self.html)
        self.assertIn(".topbar-github-link:hover", self.app_css)

    def test_volume_upload_starts_with_drop_zone_and_recovers_from_ambiguity(self) -> None:
        self.assertIn("拖入 NIfTI 或 DICOM 病例文件夹，或 ZIP 压缩包", self.html)

    def test_async_run_shows_the_backend_error_detail(self) -> None:
        self.assertIn(
            "await this.responseError(runResponse, '运行模型')",
            self.app_js,
        )
        self.assertIn("onVolumeDrop", self.html)
        self.assertIn("showVolumeCorrection", self.html)
        self.assertIn("archive_modality_selection_required", self.app_js)
        self.assertIn("请选择生效文件", self.html)
        self.assertIn("/tasks/3d/archive", self.app_js)
        self.assertIn("volumeCorrectionVisible", self.app_js)
        self.assertIn("this.volumeCorrectionVisible = false", self.app_js)
        self.assertIn("volumeSourceMenuVisible", self.html)
        self.assertIn("triggerVolumeArchivePicker", self.html)
        self.assertIn("无法读取拖入内容", self.app_js)

    def test_selected_folder_and_archive_can_be_reviewed_and_cleared(self) -> None:
        self.assertIn("已选择文件夹", self.app_js)
        self.assertIn("volumeArchiveFile || volumeDicomFiles.length", self.html)
        self.assertIn("selectedVolumeFiles", self.app_js)
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
        self.assertIn("startNewUpload()", self.app_js)
        self.assertIn("this.volumeDicomFiles = []", self.app_js)
        self.assertIn("this.activeRightView = 'results'", self.app_js)

    def test_result_integrated_view_keeps_a_case_overview_entry(self) -> None:
        self.assertIn("病例概览", self.app_js)
        self.assertIn("type: 'integrated'", self.app_js)
        self.assertIn("md-table-viewer", self.detail_html)
        self.assertNotIn("md-table-title", self.html)
        self.assertNotIn("md-table-th-key", self.html)
        self.assertNotIn("键</th>", self.html)
        self.assertNotIn("# {{ section.label }}", self.html)
        self.assertNotIn('class="copy-btn"', self.html)
        self.assertIn("label: 'frontend_result.json', path: rf.frontend", self.app_js)
        self.assertNotIn("classification.json', 'classification'", self.html)
        self.assertNotIn("segmentation.json', 'segmentation'", self.html)
        self.assertIn("flattenKeyValuePairs", self.detail_html)
        self.assertIn("visibleRows(section)", self.detail_html)
        self.assertIn("toggleRow(row)", self.detail_html)
        self.assertIn("collapsed: Boolean(hasChildren)", self.detail_html)
        self.assertIn("md-table-copy", self.detail_html)
        self.assertIn('@click="copyDetail"', self.detail_html)
        self.assertIn("rowCount", self.detail_html)
        self.assertIn("md-table-toggle", self.detail_html)

    def test_detail_table_and_toast_are_extracted_components(self) -> None:
        self.assertIn("components/btir-detail-table.js", self.html)
        self.assertIn("components/btir-toast.js", self.html)
        self.assertIn("<btir-detail-table", self.html)
        self.assertIn("<btir-toast></btir-toast>", self.html)
        self.assertIn("registry['btir-detail-table']", self.detail_html)
        self.assertIn("registry['btir-toast']", self.toast_html)
        self.assertIn("btirApp.component(name", self.app_js)
        self.assertIn("btir:toast", self.toast_html)

    def test_result_viewer_switches_between_3d_and_json(self) -> None:
        self.assertIn("viewerPane: '3d'", self.app_js)
        self.assertIn("switchViewerPane", self.app_js)
        self.assertIn("case-viewer-tabs", self.html)
        self.assertIn("switchViewerPane('3d')", self.html)
        self.assertIn("switchViewerPane('json')", self.html)
        self.assertIn("3D视图", self.html)
        self.assertIn("数据分析", self.html)
        self.assertIn("case-viewer-tab", self.html)
        self.assertIn("integratedSources", self.app_js)

    def test_login_page_synced_with_design_tokens(self) -> None:
        self.assertIn("--btir-primary:", self.theme_css)
        self.assertIn('[data-theme="dark"]', self.theme_css)
        self.assertIn("theme-toggle", self.login_html)
        self.assertIn("toggleTheme", self.login_html)
        self.assertIn(".tab:hover:not(.active)", self.login_html)
        self.assertIn("input:hover", self.auth_css)
        self.assertIn("submit-btn:hover:not(:disabled)", self.auth_css)
        self.assertNotIn("linear-gradient(180deg, #1a3a6b", self.login_html)
        self.assertNotIn("多用户认证系统", self.login_html)
        self.assertIn(".auth-card .theme-toggle", self.auth_css)
        self.assertIn("./auth.css", self.login_html)

    def test_forced_password_change_page_is_wired(self) -> None:
        self.assertIn("当前密码", self.change_password_html)
        self.assertIn("新密码", self.change_password_html)
        self.assertIn("确认新密码", self.change_password_html)
        self.assertIn("/auth/change-password", self.change_password_html)
        self.assertIn("theme-toggle", self.change_password_html)
        self.assertIn("返回登录", self.change_password_html)
        self.assertIn("window.location.href = '/web/'", self.change_password_html)
        self.assertIn("./auth.css", self.change_password_html)
        self.assertIn("data.must_change_password", self.login_html)
        self.assertIn("window.location.href = '/web/change-password.html'", self.login_html)
        self.assertIn("must_change_password", self.app_js)
        self.assertIn("window.location.href = '/web/change-password.html'", self.app_js)

    def test_reduced_motion_and_progress_color_tokens(self) -> None:
        self.assertIn("prefers-reduced-motion", self.theme_css)
        self.assertIn("--btir-progress-glow", self.theme_css)
        self.assertIn("var(--btir-progress-glow)", self.app_css)
        self.assertIn("var(--btir-primary), var(--btir-accent)", self.app_css)
        self.assertIn("var(--btir-success)", self.app_css)
        self.assertNotIn("#38a169", self.app_css)
        self.assertNotIn("#3b82f6", self.app_css)

    def test_vue_pages_hide_template_before_mount(self) -> None:
        self.assertIn("[v-cloak]", self.theme_css)
        self.assertIn('<div id="app" v-cloak>', self.html)
        self.assertIn('<div id="app" v-cloak>', self.login_html)

    def test_json_raw_tabs_removed_and_detail_results_first(self) -> None:
        self.assertNotIn("addFile('frontend_result.json'", self.html)
        self.assertNotIn("addFile('classification.json'", self.html)
        self.assertNotIn("addFile('segmentation.json'", self.html)
        self.assertLess(
            self.app_js.index("label: '病例概览'"),
            self.app_js.index("label: '3D视图'"),
        )

    def test_modern_ui_tokens_toast_skeleton_and_visualization(self) -> None:
        self.assertIn("--btir-primary:", self.theme_css)
        self.assertIn("app-toast", self.app_css)
        self.assertIn("showToastMessage", self.app_js)
        self.assertIn("task-skeleton", self.app_css)
        self.assertIn("skeleton-shimmer", self.app_css)
        self.assertIn("result-ring", self.app_css)
        self.assertIn("result-chart-line", self.app_css)
        self.assertIn("regionBarWidth", self.app_js)
        self.assertIn("probabilityPoints", self.app_js)
        self.assertIn('class="icon"', self.html)

    def test_logo_uses_theme_mask_without_frame(self) -> None:
        self.assertIn("mask: url('/assets/icon_exp.png')", self.app_css)
        self.assertIn('[data-theme="dark"] .app-logo', self.app_css)
        self.assertIn('class="app-logo"', self.html)
        self.assertNotIn("border-radius: 12px", self.html)

    def test_topbar_actions_are_embedded_icon_buttons(self) -> None:
        self.assertNotIn(">登出</button>", self.html)
        self.assertNotIn("四模态脑肿瘤 MRI 智能分析平台", self.html)
        self.assertIn('title="退出登录"', self.html)
        self.assertIn('aria-label="退出登录"', self.html)
        self.assertIn(".logout-btn:hover", self.app_css)
        self.assertIn("border-radius: 50%", self.app_css)

    def test_segmentation_judgment_uses_ring_and_legend(self) -> None:
        self.assertIn("result-ring-value seg", self.html)
        self.assertIn("segRingDashOffset", self.app_js)
        self.assertIn("segPercent", self.html)
        self.assertIn("segTotalVolume", self.html)
        self.assertIn("result-seg-legend", self.html)
        self.assertIn("result-seg-dot", self.html)

    def test_imaging_key_features_reuse_existing_segmentation_metrics(self) -> None:
        self.assertIn("影像学关键特征", self.html)
        self.assertIn("imagingKeyMetrics", self.html)
        self.assertIn("ED / WT", self.app_js)
        self.assertIn("ET / TC", self.app_js)
        self.assertIn("bounding_box_size_mm", self.app_js)
        self.assertIn("max_axial_area_mm2", self.app_js)
        self.assertIn("largest_component_ratio", self.app_js)
        self.assertIn("case-imaging-feature-meter", self.html)
        self.assertIn("case-imaging-features-grid", self.app_css)
        self.assertIn("最大横截面积", self.html)
        self.assertIn("caseInputQuality", self.app_js)

    def test_follow_up_comparison_uses_case_timeline_automatically(self) -> None:
        self.assertIn("随访对比", self.html)
        self.assertIn("follow-up-comparison", self.html)
        self.assertIn("followUpComparison", self.html)
        self.assertIn("新增复查", self.html)
        self.assertIn("follow-up-close-btn", self.html)
        self.assertIn("dismissFollowUpContext", self.app_js)
        self.assertIn("task-rename-btn", self.html)
        self.assertIn("task-rename-confirm-btn", self.html)
        self.assertIn("task-rename-cancel-btn", self.html)
        self.assertIn("重命名任务", self.html)
        self.assertIn("startTaskRename", self.app_js)
        self.assertIn("saveTaskRename", self.app_js)
        self.assertIn("检查日期", self.html)
        self.assertIn("caseId", self.app_js)
        self.assertIn("startFollowUpUpload", self.app_js)
        self.assertIn("studyDate", self.app_js)
        self.assertIn("loadFollowUpComparison", self.app_js)
        self.assertIn("/follow-up", self.app_js)
        self.assertIn("自由选择对比检查", self.html)
        self.assertIn('v-if="followUpHistoryItems.length"', self.html)
        self.assertIn("followUpHistoryItems", self.app_js)
        self.assertIn("selectFollowUpComparison", self.app_js)
        self.assertIn("isAnalysisInProgress", self.app_js)
        self.assertIn("analysis-pending", self.html)
        self.assertIn("彻底删除", self.html)
        self.assertIn("purgeArchivedTask", self.app_js)
        self.assertNotIn("设为随访基线", self.html)
        self.assertNotIn("followUpBaseline", self.app_js)
        self.assertIn("max_axial_area_mm2", self.app_js)
        self.assertIn("follow-up-bars", self.app_css)

    def test_task_flow_optimizations(self) -> None:
        self.assertNotIn("this.taskListMode = 'archived'", self.html)
        self.assertNotIn("this.taskListMode = 'archived'", self.app_js)
        self.assertNotIn("✓ 3D分析完成", self.html)
        self.assertNotIn("✓ 3D分析完成", self.app_js)
        self.assertIn(
            "statusText || analysisProgress || (analysisPolling && taskId && !analysisCancelled)",
            self.html,
        )

    def test_niivue_is_loaded_only_when_3d_viewer_opens(self) -> None:
        self.assertNotIn('href="./vendor/niivue.umd.js"', self.html)
        self.assertNotIn("BtirVolumeViewer?.preload", self.app_js)
        self.assertNotIn("preloadNiiVue", self.viewer_html)
        self.assertIn("function ensureNiiVue", self.viewer_html)
        self.assertIn("await ensureNiiVue()", self.viewer_html)

    def test_vue_is_vendored_locally_without_cdn(self) -> None:
        self.assertIn("./vendor/vue.global.js", self.html)
        self.assertIn("./vendor/vue.global.js", self.login_html)
        self.assertNotIn("unpkg.com/vue", self.html)
        self.assertNotIn("unpkg.com/vue", self.login_html)
        vendor_file = PROJECT_ROOT / "frontend" / "vendor" / "vue.global.js"
        self.assertGreater(vendor_file.stat().st_size, 100_000)
        self.assertIn("vue v3.5.41", vendor_file.read_text(encoding="utf-8"))

    def test_probability_chart_nodes_show_hover_values(self) -> None:
        self.assertIn("chartPoints", self.html)
        self.assertIn("result-chart-node", self.html)
        self.assertIn("showChartPoint", self.html)
        self.assertIn("result-chart-tooltip", self.html)
        self.assertIn("probabilityText", self.html)
        self.assertIn("chartHoverVisible", self.html)
        self.assertIn("transition: opacity 0.45s ease", self.app_css)

    def test_scroll_reveal_and_chart_draw_animations(self) -> None:
        self.assertIn("[data-reveal]", self.app_css)
        self.assertIn("initRevealObserver", self.app_js)
        self.assertIn("IntersectionObserver", self.app_js)
        self.assertIn("ringDisplayOffset", self.app_js)
        self.assertIn("segRingDisplayOffset", self.app_js)
        self.assertIn("probLineLength", self.app_js)
        self.assertIn("probLineDrawn", self.app_js)
        self.assertIn("animationDelay", self.html)
        self.assertIn("animation: fade-in 0.2s ease", self.app_css)

    def test_detail_table_translates_json_keys_to_chinese(self) -> None:
        self.assertIn("KEY_LABELS", self.detail_html)
        self.assertIn("translateKey", self.detail_html)
        self.assertIn("rawKey", self.detail_html)
        self.assertIn("分类结果", self.detail_html)
        self.assertIn("协议版本", self.detail_html)
        self.assertIn("置信度", self.detail_html)

    def test_detail_table_uses_curated_sections(self) -> None:
        self.assertIn("buildCuratedRows", self.detail_html)
        self.assertIn("addGroup('分类判断'", self.detail_html)
        self.assertIn("addGroup('分割判断'", self.detail_html)
        self.assertIn("addGroup('模型共识'", self.detail_html)
        self.assertIn("addGroup('综合分析'", self.detail_html)
        self.assertNotIn("addGroup('任务信息'", self.detail_html)
        self.assertNotIn("addGroup('性能耗时'", self.detail_html)
        self.assertNotIn("addGroup('全部字段'", self.detail_html)
        self.assertNotIn("addLeaf('model',", self.detail_html)
        self.assertNotIn("addGroup('空间信息'", self.detail_html)
        self.assertNotIn("addLeaf('voxels'", self.detail_html)

    def test_detail_table_expands_doctor_relevant_sections_by_default(self) -> None:
        self.assertIn("addGroup('分类判断', 0, false", self.detail_html)
        self.assertIn("addGroup('综合分析', 0, false", self.detail_html)
        self.assertIn("addGroup('分割判断', 0, true", self.detail_html)
        self.assertIn("addGroup('模型共识', 0, true", self.detail_html)
        self.assertIn("addGroup('观察项', 1, true", self.detail_html)

    def test_case_overview_cards_and_preview_are_wired(self) -> None:
        self.assertIn("tumorComposites", self.app_js)
        self.assertIn("tumorMorphology", self.app_js)
        self.assertIn("casePreviewPath", self.app_js)
        self.assertIn("casePreviewFrames", self.app_js)
        self.assertIn("casePreviewMode", self.app_js)
        self.assertIn("slicePositiveRatio", self.app_js)
        self.assertIn("resultFiles.preview", self.app_js)
        self.assertIn("resultFiles.preview_series", self.app_js)
        self.assertIn("case-overview", self.html)
        self.assertIn("volume-stack", self.html)
        self.assertIn("morph-bar", self.html)
        self.assertIn("result-chart-wrap", self.html)
        self.assertIn("切片概率分布", self.html)
        self.assertIn("case-preview-img", self.html)
        self.assertIn("原始四模态", self.html)
        self.assertIn("分割叠加", self.html)
        self.assertIn("case-preview-nav", self.html)
        self.assertIn("case-overview-ring", self.html)
        self.assertIn("case-prob-expanded", self.html)
        self.assertIn("data-ring=\"classification\"", self.html)
        self.assertIn("data-ring=\"segmentation\"", self.html)
        self.assertIn("data-ring=\"probability\"", self.html)
        self.assertIn("void this.openCaseVolumeViewer()", self.app_js)
        self.assertIn("deferCaseVolumeViewer", self.app_js)
        self.assertIn("deferredVolumeLoadTimer", self.app_js)
        self.assertIn("}, 1500)", self.app_js)
        self.assertNotIn("case-preview-3d-btn", self.html)
        self.assertIn("returnToCaseOverview", self.app_js)
        self.assertIn("caseDataColumn?.scrollTo", self.app_js)
        self.assertIn("3D 查看器未完成初始化", self.app_js)
        self.assertIn(".case-overview", self.app_css)
        preview_service = PROJECT_ROOT / "services" / "case_preview.py"
        self.assertTrue(preview_service.is_file())
        self.assertIn("PREVIEW = \"preview.png\"", (
            PROJECT_ROOT / "core" / "task_definitions.py"
        ).read_text(encoding="utf-8"))

    def test_result_workspace_allows_resizing_the_viewer_and_analysis_columns(self) -> None:
        self.assertIn("result-column-resizer", self.html)
        self.assertIn("startResultSplitResize", self.html)
        self.assertIn("resultSplitStyle", self.html)
        self.assertIn("resultSplitRatio", self.app_js)
        self.assertIn("btir_result_split_ratio", self.app_js)
        self.assertIn("updateResultSplitFromPointer", self.app_js)
        self.assertIn(".result-column-resizer", self.app_css)
        self.assertIn("--btir-result-data-width", self.app_css)
        self.assertIn("container-type: inline-size", self.app_css)
        self.assertIn("@container (max-width: 540px)", self.app_css)

    def test_detailed_result_merged_with_graphical_sections(self) -> None:
        self.assertIn("analysis-summary", self.html)
        self.assertIn("AI 辅助分析", self.html)
        self.assertIn("region-overview", self.html)
        self.assertIn("分割区域", self.html)
        self.assertIn("case-meta-section", self.html)
        self.assertIn("查看详细数据", self.html)
        self.assertIn("case-meta-summary", self.html)
        self.assertIn("prob-bar", self.html)
        self.assertIn("切片概率分布", self.html)
        self.assertNotIn("clinical-details", self.html)
        self.assertNotIn("md-table-viewer", self.html)
        self.assertNotIn("病灶体积", self.html)
        self.assertNotIn("形态与定位", self.html)
        self.assertIn("classProbabilities", self.app_js)
        self.assertIn("tumorSpatial", self.app_js)
        self.assertIn("compositeBarWidth", self.app_js)

    def test_sample_download_entry_near_upload(self) -> None:
        self.assertIn("sample-download", self.html)
        self.assertIn("sample-download-link", self.html)
        self.assertIn("去下载测试样例", self.html)
        self.assertNotIn("48.5 MB", self.html)
        self.assertIn("评委测试包", self.guide_html)

    def test_sample_download_opens_guide_subpage(self) -> None:
        self.assertIn("openSampleGuide", self.html)
        self.assertIn("window.location.href = 'guide.html'", self.app_js)
        self.assertIn("guide-back", self.guide_html)
        self.assertIn("guide-download", self.guide_html)
        self.assertIn("guideTheme", self.guide_html)
        self.assertIn("renderMarkdown", self.guide_html)
        self.assertIn("formatFileSize", self.guide_html)
        self.assertIn("method: 'HEAD'", self.guide_html)
        self.assertIn("cache: 'no-store'", self.guide_html)
        self.assertIn("window.setInterval(updateDownloadMeta, 30_000)", self.guide_html)
        self.assertIn("visibilitychange", self.guide_html)
        self.assertIn("/assets/guide.md", self.guide_html)
        self.assertIn("guide-download-meta", self.guide_html)
        self.assertNotIn("48.5 MB", self.guide_html)
        self.assertIn("window.location.href = 'index.html'", self.guide_html)
        self.assertNotIn("guide-md-source", self.guide_html)

    def test_guide_markdown_supports_blockquote_and_images(self) -> None:
        self.assertIn("'<blockquote>'", self.guide_html)
        self.assertIn("resolveAsset", self.guide_html)
        self.assertIn(
            '<img src="${resolveAsset(src)}" alt="${alt}" loading="lazy">',
            self.guide_html,
        )
        self.assertIn(".guide-md blockquote", self.guide_html)
        self.assertIn(".guide-md img", self.guide_html)

    def test_upload_menu_closes_on_outside_click(self) -> None:
        self.assertIn("ref=\"volumeDropZone\"", self.html)
        self.assertIn("handleGlobalClick", self.app_js)
        self.assertIn("document.addEventListener('click', this.handleGlobalClick)", self.app_js)
        self.assertIn("document.removeEventListener('click', this.handleGlobalClick)", self.app_js)


if __name__ == "__main__":
    unittest.main()
