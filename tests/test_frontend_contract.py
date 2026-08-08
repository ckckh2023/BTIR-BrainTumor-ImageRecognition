'''前端任务操作与 3D 结果展示的轻量契约回归测试'''

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
        self.assertIn("analysisProgressPercent", self.html)
        self.assertIn("resultData.progress_stage", self.app_js)

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
        self.assertIn("analysisConsistencyLabel", self.html)
        self.assertIn("分析模型：", self.html)
        self.assertIn("supplementaryRecommendation(supplementaryAnalysis)", self.html)
        self.assertIn("supplementaryRecommendation(analysis)", self.app_js)
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
        self.assertIn(".left-panel", self.app_css)
        self.assertIn(".left-panel-scroll", self.app_css)
        self.assertIn("overflow-y: auto;", self.app_css)
        self.assertIn(".result-section", self.app_css)
        self.assertIn("flex: 1 1 auto;", self.app_css)
        self.assertIn("min-height: 280px;", self.app_css)

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
        self.assertIn('class="result-section" v-if="taskId || analysisActive"', self.html)
        self.assertIn("analysisActive: false", self.app_js)
        self.assertIn("this.analysisActive = true", self.app_js)
        self.assertIn("this.analysisActive = false", self.app_js)

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

    def test_result_integrated_view_flattens_json_key_value_pairs(self) -> None:
        self.assertIn("详细结果", self.app_js)
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

    def test_login_page_synced_with_design_tokens(self) -> None:
        self.assertIn("--btir-primary:", self.theme_css)
        self.assertIn('[data-theme="dark"]', self.theme_css)
        self.assertIn("theme-toggle", self.login_html)
        self.assertIn("toggleTheme", self.login_html)
        self.assertIn(".tab:hover:not(.active)", self.login_html)
        self.assertIn("input:hover", self.login_html)
        self.assertIn("submit-btn:hover:not(:disabled)", self.login_html)
        self.assertNotIn("linear-gradient(180deg, #1a3a6b", self.login_html)
        self.assertNotIn("多用户认证系统", self.login_html)
        self.assertIn(".auth-card .theme-toggle", self.login_html)

    def test_json_raw_tabs_removed_and_detail_results_first(self) -> None:
        self.assertNotIn("addFile('frontend_result.json'", self.html)
        self.assertNotIn("addFile('classification.json'", self.html)
        self.assertNotIn("addFile('segmentation.json'", self.html)
        self.assertLess(
            self.app_js.index("label: '详细结果'"),
            self.app_js.index("label: '3D查看'"),
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

    def test_task_flow_optimizations(self) -> None:
        self.assertNotIn("this.taskListMode = 'archived'", self.html)
        self.assertNotIn("this.taskListMode = 'archived'", self.app_js)
        self.assertNotIn("✓ 3D分析完成", self.html)
        self.assertNotIn("✓ 3D分析完成", self.app_js)
        self.assertIn(
            "statusText || analysisProgress || (analysisPolling && taskId && !analysisCancelled)",
            self.html,
        )

    def test_niivue_preload_warms_3d_viewer(self) -> None:
        self.assertIn(
            '<link rel="preload" href="./vendor/niivue.umd.js" as="script">',
            self.html,
        )
        self.assertIn("window.BtirVolumeViewer?.preload?.()", self.app_js)
        self.assertIn("global.BtirVolumeViewer.preload = preloadNiiVue", self.viewer_html)
        self.assertIn("function preloadNiiVue", self.viewer_html)

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
        self.assertIn("addGroup('任务信息'", self.detail_html)
        self.assertIn("addGroup('分类判断'", self.detail_html)
        self.assertIn("addGroup('分割判断'", self.detail_html)
        self.assertIn("addGroup('模型共识'", self.detail_html)
        self.assertIn("addGroup('综合分析'", self.detail_html)
        self.assertIn("addGroup('性能耗时'", self.detail_html)
        self.assertIn("addGroup('全部字段'", self.detail_html)

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
