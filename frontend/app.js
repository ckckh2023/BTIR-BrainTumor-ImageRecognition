        const { createApp } = Vue

        const btirRootOptions = {
            data() {
                return {
                    API_BASE: '',
                    loading: false,
                    analysisCancelled: false,
                    analysisPolling: false,
                    analysisProgress: null,
                    displayProgress: 0,
                    progressAnimFrame: null,
                    progressMotionActive: false,
                    statusText: '等待识别...',
                    taskId: '',
                    analysisActive: false,
                    tumorComposites: {},
                    tumorMorphology: {},
                    tumorSpatial: {},
                    classProbabilities: {},
                    caseInputFiles: {},
                    followUp: null,
                    selectedFollowUpTaskId: '',
                    casePreviewPath: '',
                    casePreviewUrl: '',
                    casePreviewFrames: [],
                    casePreviewUrls: {},
                    casePreviewMode: 'overlay',
                    casePreviewActiveIndex: 0,
                    casePreviewDirection: 1,
                    casePreviewRequestId: 0,
                    casePreviewFullscreen: false,
                    volumeModalities: [
                        { key: 'flair', label: 'FLAIR' },
                        { key: 't1ce', label: 'T1CE' },
                        { key: 't1', label: 'T1' },
                        { key: 't2', label: 'T2' },
                    ],
                    volumeFiles: {
                        flair: null,
                        t1ce: null,
                        t1: null,
                        t2: null,
                    },
                    volumeArchiveFile: null,
                    volumeDicomFiles: [],
                    volumeFolderLabel: '',
                    caseId: '',
                    caseName: '',
                    followUpContextDismissed: false,
                    studyDate: new Date().toISOString().slice(0, 10),
                    volumeDropActive: false,
                    volumeSourceMenuVisible: false,
                    volumeCaseSourceMenuVisible: false,
                    volumeManualMode: false,
                    volumeSelectionIssues: {},
                    volumeSelectionCandidates: {},
                    volumeCandidateSelections: {},
                    archiveSelections: {},
                    dicomSeriesCandidates: {},
                    dicomSeriesSelections: {},
                    volumeCorrectionVisible: true,
                    classificationLabel: '',
                    confidence: 0,
                    tumorArea: null,
                    regionStats: [],
                    modelConsensus: null,
                    supplementaryAnalysis: null,
                    fileList: [],
                    downloadFiles: [],
                    exportingReport: false,
                    selectedFilePath: '',
                    selectedFileType: '',
                    integratedSources: [],
                    probabilitySeries: [],
                    probabilityThreshold: 0.548381,
                    chartHover: null,
                    chartHoverVisible: false,
                    ringRevealed: false,
                    segRingRevealed: false,
                    probLineRevealed: false,
                    probLineLength: 0,
                    probLineDrawn: false,
                    volumeViewer: null,
                    volumeViewerSources: null,
                    volumeViewerLoading: false,
                    volumeViewerError: '',
                    volumeDownload: null,
                    selectedVolumeModality: 'flair',
                    volumeMaskVisible: true,
                    volumeMaskOpacity: 0.55,
                    volumeViewMode: 'multiplanar',
                    volumeViewerExpanded: false,
                    deferredVolumeLoadTimer: null,
                    resultSplitRatio: (() => {
                        try {
                            const value = Number(localStorage.getItem('btir_result_split_ratio'))
                            return Number.isFinite(value) && value >= 0.4 && value <= 0.68
                                ? value
                                : 0.618
                        } catch {
                            return 0.618
                        }
                    })(),
                    resultSplitViewportWidth: 0,
                    resultSplitDragging: false,
                    resultSplitDrawFrame: null,
                    activeRightView: (() => {
                        try {
                            const url = new URL(window.location.href)
                            const urlView = url.searchParams.get('view')
                            if (urlView === 'tasks') return 'tasks'
                            const savedWorkspace = JSON.parse(
                                sessionStorage.getItem('btir_workspace')
                                || localStorage.getItem('btir_workspace')
                                || 'null',
                            )
                            return savedWorkspace?.view === 'tasks' ? 'tasks' : 'results'
                        } catch {
                            return 'results'
                        }
                    })(),
                    viewerPane: '3d',
                    taskItems: [],
                    taskTotal: 0,
                    taskLimit: 10,
                    taskOffset: 0,
                    taskQuery: '',
                    taskStatusFilter: '',
                    taskHistoryRequestId: 0,
                    taskListMode: 'active',
                    taskHistoryLoading: false,
                    taskActionId: '',
                    taskRunHistoryTaskId: '',
                    taskRunHistoryItems: [],
                    taskRunHistoryLoading: false,
                    taskRenameTaskId: '',
                    taskRenameDraft: '',
                    taskMessage: '',
                    taskMessageIsError: false,
                    currentUser: null,
                    theme: 'light',
                    workspaceRestoring: (() => {
                        try {
                            const url = new URL(window.location.href)
                            return Boolean(
                                url.searchParams.get('task')
                                || url.searchParams.get('view')
                                || sessionStorage.getItem('btir_workspace')
                                || localStorage.getItem('btir_workspace'),
                            )
                        } catch {
                            return false
                        }
                    })(),
                }
            },
            computed: {
                volumeDownloadLabel() {
                    const download = this.volumeDownload
                    if (!download) {
                        return '读取并解析 NIfTI 数据...'
                    }
                    if (
                        !download.indeterminate
                        && download.total > 0
                        && download.loaded >= download.total
                    ) {
                        return '下载完成，正在解析 NIfTI 数据...'
                    }
                    if (
                        !download.indeterminate
                        && download.total > 0
                        && download.label
                    ) {
                        return `正在下载 ${download.label}...`
                    }
                    return '正在下载体数据...'
                },
                volumeDownloadPercent() {
                    const download = this.volumeDownload
                    if (!download || !download.total) return 0
                    return Math.min(
                        100,
                        Math.max(
                            0,
                            Math.round((download.loaded / download.total) * 100)
                        )
                    )
                },
                mappedProgressPercent() {
                    const progress = this.analysisProgress
                    if (!progress || typeof progress.percent !== 'number') return 0
                    const raw = Math.min(100, Math.max(0, progress.percent))
                    let mapped
                    if (raw < 36) {
                        mapped = (raw / 36) * 30
                    } else if (raw < 44) {
                        mapped = 30 + ((raw - 36) / 8) * 25
                    } else if (raw < 98) {
                        mapped = 55 + ((raw - 44) / 54) * 35
                    } else {
                        mapped = 90 + ((raw - 98) / 2) * 10
                    }
                    return Math.min(100, Math.max(0, mapped))
                },
                progressPhaseCeiling() {
                    const real = this.analysisProgress?.percent
                    if (typeof real !== 'number') return 100
                    if (real >= 100) return 100
                    if (real >= 98) return 100
                    if (real >= 44) return 90
                    return 55
                },
                analysisProgressLabel() {
                    return this.analysisProgress?.stage || '推理中...'
                },
                analysisPhases() {
                    if (!this.analysisPolling || !this.taskId) return []
                    const p = this.analysisProgress?.percent
                    if (p === undefined || p === null) return []
                    const reached = (value) => p >= value
                    return [
                        {
                            key: 'classification',
                            label: '3D 分类',
                            state: reached(44) ? 'done' : 'active',
                        },
                        {
                            key: 'segmentation',
                            label: '3D 分割',
                            state: reached(99)
                                ? 'done'
                                : (reached(44) ? 'active' : 'pending'),
                        },
                        {
                            key: 'summary',
                            label: '综合分析',
                            state: reached(100)
                                ? 'done'
                                : (reached(99) ? 'active' : 'pending'),
                        },
                    ]
                },
                taskPage() {
                    return Math.floor(this.taskOffset / this.taskLimit) + 1
                },
                taskPageCount() {
                    return Math.max(1, Math.ceil(this.taskTotal / this.taskLimit))
                },
                isAnalysisInProgress() {
                    return Boolean(this.loading || this.analysisActive || this.analysisPolling)
                },
                taskCaseGroups() {
                    const groups = new Map()
                    for (const task of this.taskItems) {
                        const caseId = task.case_id || task.task_id
                        if (!groups.has(caseId)) {
                            groups.set(caseId, {
                                caseId,
                                name: task.case_name || task.name || '未命名病例',
                                tasks: [],
                            })
                        }
                        groups.get(caseId).tasks.push(task)
                    }
                    return [...groups.values()]
                },
                authHeaders() {
                    const token = localStorage.getItem('btir_token')
                    return token ? { 'Authorization': `Bearer ${token}` } : {}
                },
                canRecognize() {
                    if (this.hasPendingDicomSeriesSelection) {
                        return Object.keys(this.dicomSeriesCandidates).every(
                            modality => Boolean(this.dicomSeriesSelections[modality])
                        )
                    }
                    if (this.volumeDicomFiles.length) return true
                    if (this.volumeArchiveFile) {
                        return this.volumeModalities.every(modality => (
                            !this.volumeSelectionIssues[modality.key]
                            || Boolean(this.volumeFiles[modality.key])
                            || Boolean(this.archiveSelections[modality.key])
                        ))
                    }
                    return this.volumeModalities.every(
                        modality => Boolean(this.volumeFiles[modality.key])
                    )
                },
                showVolumeCorrection() {
                    return this.volumeCorrectionVisible
                        && Object.keys(this.volumeSelectionIssues).length > 0
                },
                hasVolumeFolderSelection() {
                    return !this.volumeArchiveFile
                        && !this.volumeDicomFiles.length
                        && Boolean(this.volumeFolderLabel)
                },
                hasPendingDicomSeriesSelection() {
                    return Object.keys(this.dicomSeriesCandidates).length > 0
                },
                isResultWorkspace() {
                    return Boolean(
                        this.activeRightView === 'tasks'
                        || (
                            this.taskId
                            && !this.loading
                            && ['integrated', 'volume'].includes(this.selectedFileType)
                        ),
                    )
                },
                hasRightPanel() {
                    return this.activeRightView === 'tasks'
                        || Boolean(this.selectedFileType || this.fileList.length)
                },
                resultSplitStyle() {
                    const width = this.resultSplitViewportWidth
                    const availableWidth = width - 16
                    if (availableWidth < 760) return {}
                    const dataWidth = Math.min(
                        availableWidth - 360,
                        Math.max(360, availableWidth * this.resultSplitRatio),
                    )
                    return { '--btir-result-data-width': `${Math.round(dataWidth)}px` }
                },
                volumeSourceSummary() {
                    if (this.volumeArchiveFile) {
                        return `已选择压缩包：${this.volumeArchiveFile.name}`
                    }
                    if (this.volumeDicomFiles.length) {
                        return `已选择 DICOM 文件夹：${this.volumeFolderLabel}（${this.volumeDicomFiles.length} 个文件）`
                    }
                    if (this.hasVolumeFolderSelection) {
                        return `已选择文件夹：${this.volumeFolderLabel}`
                    }
                    if (this.volumeManualMode) {
                        return '手动上传四个 NIfTI 文件'
                    }
                    return ''
                },
                volumeModalFilesVisible() {
                    if (this.showVolumeCorrection) return false
                    if (this.volumeDicomFiles.length) return false
                    if (this.volumeManualMode || this.hasVolumeFolderSelection) return true
                    if (this.volumeArchiveFile) {
                        return this.volumeModalities.some(modality =>
                            Boolean(this.volumeFiles[modality.key])
                            || Boolean(this.archiveSelections[modality.key])
                        )
                    }
                    return false
                },
                selectedVolumeFiles() {
                    return this.volumeModalities
                        .map(modality => this.volumeFiles[modality.key])
                        .filter(Boolean)
                },
                availableVolumeModalities() {
                    const sources = this.volumeViewerSources?.modalities || {}
                    return this.volumeModalities.filter(
                        modality => Boolean(sources[modality.key])
                    )
                },
                ringCircumference() {
                    return 2 * Math.PI * 26
                },
                ringDashOffset() {
                    const ratio = Math.max(0, Math.min(1, this.confidence || 0))
                    return this.ringCircumference * (1 - ratio)
                },
                ringDisplayOffset() {
                    return this.ringRevealed ? this.ringDashOffset : this.ringCircumference
                },
                ringPercent() {
                    return Math.round((this.confidence || 0) * 1000) / 10
                },
                segRingDashOffset() {
                    const ratio = Math.max(0, Math.min(1, this.tumorArea || 0))
                    return this.ringCircumference * (1 - ratio)
                },
                segRingDisplayOffset() {
                    return this.segRingRevealed ? this.segRingDashOffset : this.ringCircumference
                },
                segPercent() {
                    return Math.round((this.tumorArea || 0) * 1000) / 10
                },
                segTotalVolume() {
                    return this.regionStats.reduce(
                        (sum, region) => sum + region.volumeMm3,
                        0,
                    )
                },
                imagingKeyMetrics() {
                    const compositeVolume = key => {
                        const value = Number(this.tumorComposites[key]?.volume_mm3)
                        return Number.isFinite(value) && value >= 0 ? value : null
                    }
                    const regionVolume = label => {
                        const value = this.regionStats.find(region => region.label === label)?.volumeMm3
                        return Number.isFinite(value) && value >= 0 ? value : null
                    }
                    const percentage = (part, whole) => (
                        Number.isFinite(part) && Number.isFinite(whole) && whole > 0
                            ? Math.max(0, Math.min(100, part / whole * 100))
                            : null
                    )
                    const metrics = []
                    const dimensions = this.tumorMorphology.bounding_box_size_mm
                    if (Array.isArray(dimensions) && dimensions.length === 3) {
                        const values = dimensions.map(Number)
                        if (values.every(value => Number.isFinite(value) && value > 0)) {
                            const longest = Math.max(...values)
                            metrics.push({
                                key: 'extent',
                                tone: 'extent',
                                label: '病灶范围',
                                tag: '三维大小',
                                value: `${Math.round(longest)} mm`,
                                detail: `${values.map(value => Math.round(value)).join(' × ')} mm`,
                                meter: null,
                                meterLabel: '',
                            })
                        }
                    }

                    const maxAxialArea = Number(this.tumorMorphology.max_axial_area_mm2)
                    const maxAxialSlice = Number(this.tumorMorphology.max_axial_slice_index)
                    if (Number.isFinite(maxAxialArea) && maxAxialArea > 0) {
                        metrics.push({
                            key: 'axial-area',
                            tone: 'area',
                            label: '最大横截面积',
                            tag: '轴位切面',
                            value: `${this.formatVolume(maxAxialArea)} mm²`,
                            detail: Number.isFinite(maxAxialSlice)
                                ? `对应切片 ${Math.round(maxAxialSlice)}`
                                : '对应最大病灶层',
                            meter: null,
                            meterLabel: '',
                        })
                    }

                    const wholeTumor = compositeVolume('WT')
                    const edema = regionVolume('2')
                    const edemaRatio = percentage(edema, wholeTumor)
                    if (edemaRatio !== null) {
                        metrics.push({
                            key: 'edema',
                            tone: 'edema',
                            label: '瘤周水肿',
                            tag: 'ED / WT',
                            value: `${edemaRatio.toFixed(1)}%`,
                            detail: `ED ${this.formatVolume(edema)} mm³，占全病灶`,
                            meter: edemaRatio,
                            meterLabel: '水肿体积占比',
                        })
                    }

                    const tumorCore = compositeVolume('TC')
                    const enhancingTumor = compositeVolume('ET')
                    const enhancingRatio = percentage(enhancingTumor, tumorCore)
                    if (enhancingRatio !== null) {
                        metrics.push({
                            key: 'enhancement',
                            tone: 'enhancement',
                            label: '强化成分',
                            tag: 'ET / TC',
                            value: `${enhancingRatio.toFixed(1)}%`,
                            detail: `ET ${this.formatVolume(enhancingTumor)} mm³，占肿瘤核心`,
                            meter: enhancingRatio,
                            meterLabel: '强化区域体积占比',
                        })
                    }

                    const components = Number(this.tumorMorphology.connected_components)
                    const dominantRatio = Number(this.tumorMorphology.largest_component_ratio)
                    if (Number.isFinite(components) && components > 0 && Number.isFinite(dominantRatio)) {
                        const ratio = Math.max(0, Math.min(100, dominantRatio * 100))
                        metrics.push({
                            key: 'distribution',
                            tone: 'distribution',
                            label: '空间分布',
                            tag: '连通性',
                            value: `主体 ${ratio.toFixed(1)}%`,
                            detail: `${Math.round(components)} 个分割连通域`,
                            meter: ratio,
                            meterLabel: '最大连通域占比',
                        })
                    }
                    return metrics
                },
                followUpComparison() {
                    const selected = this.selectedFollowUpItem
                    const baseline = selected?.task
                    const baselineResult = selected?.frontend_result
                    if (!baseline || !baselineResult || !this.taskId || baseline.task_id === this.taskId) {
                        return null
                    }
                    const currentResult = {
                        classification: {
                            probabilities: this.classProbabilities,
                        },
                        segmentation: {
                            composites: this.tumorComposites,
                            morphology: this.tumorMorphology,
                        },
                    }
                    const compositeValue = (result, key) => {
                        const value = Number(result?.segmentation?.composites?.[key]?.volume_mm3)
                        return Number.isFinite(value) && value >= 0 ? value : null
                    }
                    const morphologyValue = (result, key) => {
                        const value = Number(result?.segmentation?.morphology?.[key])
                        return Number.isFinite(value) && value >= 0 ? value : null
                    }
                    const probabilityValue = result => {
                        const value = Number(result?.classification?.probabilities?.yes)
                        return Number.isFinite(value) && value >= 0 ? value : null
                    }
                    const makeMetric = (key, label, unit, baselineValue, currentValue, formatter) => {
                        if (baselineValue === null || currentValue === null) return null
                        const change = currentValue - baselineValue
                        const percent = baselineValue > 0 ? change / baselineValue * 100 : null
                        return {
                            key,
                            label,
                            unit,
                            baselineValue,
                            currentValue,
                            baseline: formatter(baselineValue),
                            current: formatter(currentValue),
                            change,
                            changeText: this.formatFollowUpChange(change, percent, unit),
                            tone: this.followUpChangeTone(change),
                        }
                    }
                    const volumeFormatter = value => `${this.formatVolume(value)} mm³`
                    const areaFormatter = value => `${this.formatVolume(value)} mm²`
                    const probabilityFormatter = value => `${(value * 100).toFixed(1)}%`
                    const metrics = [
                        makeMetric('wt', '全肿瘤体积', 'volume', compositeValue(baselineResult, 'WT'), compositeValue(currentResult, 'WT'), volumeFormatter),
                        makeMetric('tc', '肿瘤核心体积', 'volume', compositeValue(baselineResult, 'TC'), compositeValue(currentResult, 'TC'), volumeFormatter),
                        makeMetric('et', '强化肿瘤体积', 'volume', compositeValue(baselineResult, 'ET'), compositeValue(currentResult, 'ET'), volumeFormatter),
                        makeMetric('area', '最大横截面积', 'area', morphologyValue(baselineResult, 'max_axial_area_mm2'), morphologyValue(currentResult, 'max_axial_area_mm2'), areaFormatter),
                        makeMetric('probability', '肿瘤相关概率', 'probability', probabilityValue(baselineResult), probabilityValue(currentResult), probabilityFormatter),
                    ].filter(Boolean)
                    if (!metrics.length) return null
                    const wt = metrics.find(metric => metric.key === 'wt')
                    const chartMax = wt ? Math.max(wt.baselineValue, wt.currentValue, 1) : 1
                    return {
                        baseline,
                        metrics,
                        trend: wt
                            ? [
                                { label: '基线', value: wt.baselineValue, display: wt.baseline, height: wt.baselineValue / chartMax * 100 },
                                { label: '本次', value: wt.currentValue, display: wt.current, height: wt.currentValue / chartMax * 100 },
                            ]
                            : [],
                    }
                },
                followUpHistoryItems() {
                    const history = this.followUp?.history
                    if (Array.isArray(history) && history.length) return history
                    if (this.followUp?.baseline && this.followUp?.baseline_frontend_result) {
                        return [{
                            task: this.followUp.baseline,
                            frontend_result: this.followUp.baseline_frontend_result,
                        }]
                    }
                    return []
                },
                selectedFollowUpItem() {
                    const history = this.followUpHistoryItems
                    return history.find(item => item.task?.task_id === this.selectedFollowUpTaskId)
                        || history[0]
                        || null
                },
                followUpUsesRecommendedBaseline() {
                    return Boolean(
                        this.followUp?.baseline?.task_id
                        && this.selectedFollowUpItem?.task?.task_id === this.followUp.baseline.task_id,
                    )
                },
                caseInputQuality() {
                    const present = this.volumeModalities.filter(
                        modality => Boolean(this.caseInputFiles[modality.key]),
                    )
                    if (!present.length) return null
                    const missing = this.volumeModalities
                        .filter(modality => !this.caseInputFiles[modality.key])
                        .map(modality => modality.label)
                    return {
                        present: present.map(modality => modality.label),
                        missing,
                        complete: missing.length === 0,
                    }
                },
                activeCasePreviewFrame() {
                    return this.casePreviewFrames[this.casePreviewActiveIndex] || null
                },
                activeCasePreviewPath() {
                    const frame = this.activeCasePreviewFrame
                    if (!frame) return ''
                    return this.casePreviewMode === 'raw' && frame.raw
                        ? frame.raw
                        : frame.overlay
                },
                casePreviewHasRaw() {
                    return this.casePreviewFrames.some(frame => Boolean(frame.raw))
                },
                casePreviewCaption() {
                    const frame = this.activeCasePreviewFrame
                    if (!frame) return ''
                    const position = frame.offset === 0
                        ? '最大病灶层'
                        : (frame.offset < 0 ? '最大病灶层前一层' : '最大病灶层后一层')
                    const source = this.casePreviewMode === 'raw'
                        ? '四模态原始切片'
                        : '四模态切片与分割叠加'
                    const slice = Number.isInteger(frame.sliceIndex)
                        ? ` · 切片 ${frame.sliceIndex}`
                        : ''
                    return `${position}${slice}　${source}`
                },
                consensusCard() {
                    const consensus = this.modelConsensus
                    if (!consensus) return null
                    const classificationPositive = this.classificationLabel === '肿瘤 detected'
                    const segmentationDetected = Boolean(consensus.segmentation_detected)
                    const fallbackLevel = segmentationDetected && classificationPositive
                        ? 'high_probability_present'
                        : (segmentationDetected || classificationPositive
                            ? 'possible_present'
                            : 'likely_absent')
                    const level = consensus.level || fallbackLevel
                    const positiveProbability = Number(
                        consensus.classification_positive_probability
                    )
                    const fallbackPositiveProbability = Number(this.classProbabilities.yes)
                    const positive = Number.isFinite(positiveProbability)
                        ? positiveProbability
                        : fallbackPositiveProbability
                    const classificationText = Number.isFinite(positive)
                        ? `${positive >= 0.5 ? '提示异常' : '倾向正常'} ${(Math.abs(positive >= 0.5 ? positive : 1 - positive) * 100).toFixed(1)}%`
                        : (this.classificationLabel === '肿瘤 detected' ? '提示异常' : '倾向正常')
                    const volume = Number(consensus.segmentation_volume_mm3)
                    const ratio = Number(consensus.segmentation_ratio)
                    const segmentationText = consensus.segmentation_detected
                        ? `检出区域${Number.isFinite(ratio) && ratio > 0 ? ` · 占比 ${(ratio * 100).toFixed(2)}%` : ''}${Number.isFinite(volume) && volume > 0 ? ` · ${this.formatVolume(volume)} mm³` : ''}`
                        : '未检出区域'
                    const tone = {
                        high_probability_present: 'present',
                        possible_present: 'possible',
                        likely_absent: 'absent',
                        high_probability_absent: 'absent',
                        inconclusive: 'review',
                    }[level] || (consensus.requires_review ? 'review' : 'present')
                    const fallbackLabel = {
                        high_probability_present: '高概率存在肿瘤相关区域',
                        possible_present: '存在肿瘤相关区域的可能',
                        likely_absent: '倾向不存在肿瘤相关区域',
                        high_probability_absent: '高概率不存在肿瘤相关区域',
                        inconclusive: '综合结果待确认',
                    }[level]
                    return {
                        label: consensus.label || fallbackLabel,
                        summary: consensus.summary || '正在汇总分类与分割结果',
                        classificationText,
                        segmentationText,
                        consistencyText: consensus.consistency === 'consistent'
                            ? '两模型结果相互支持'
                            : '两模型结果存在差异',
                        tone,
                    }
                },
                hasSupplementaryAnalysis() {
                    const analysis = this.supplementaryAnalysis
                    const content = analysis?.content
                    if (analysis?.status !== 'succeeded' || !content) return false
                    return Boolean(
                        content.summary
                        || content.follow_up
                        || content.uncertainties?.length
                        || content.observations?.length
                    )
                },
                thresholdText() {
                    return `${Math.round((this.probabilityThreshold || 0) * 1000) / 10}%`
                },
                probabilityPoints() {
                    const series = this.probabilitySeries
                    if (!Array.isArray(series) || series.length < 2) return ''
                    return series.map((item, index) => {
                        const x = (index / (series.length - 1)) * 280
                        const ratio = Math.max(0, Math.min(1, Number(item.yes_probability) || 0))
                        const y = 94 - ratio * 90
                        return `${x.toFixed(2)},${y.toFixed(2)}`
                    }).join(' ')
                },
                chartPoints() {
                    const series = this.probabilitySeries
                    if (!Array.isArray(series) || series.length < 2) return []
                    return series.map((item, index) => {
                        const ratio = Math.max(0, Math.min(1, Number(item.yes_probability) || 0))
                        return {
                            index,
                            sliceIndex: item.slice_index,
                            probability: ratio,
                            x: (index / (series.length - 1)) * 280,
                            y: 94 - ratio * 90,
                        }
                    })
                },
                probabilityThresholdY() {
                    const ratio = Math.max(0, Math.min(1, this.probabilityThreshold || 0))
                    return 94 - ratio * 90
                },
                slicePositiveRatio() {
                    if (!this.probabilitySeries.length) return null
                    const threshold = this.probabilityThreshold || 0
                    const hits = this.probabilitySeries.filter(
                        value => Number(value?.yes_probability) >= threshold,
                    ).length
                    return hits / this.probabilitySeries.length
                },
            },
            watch: {
                analysisProgress: {
                    deep: true,
                    handler() {
                        this.startProgressMotion()
                    },
                },
                probLineRevealed(value) {
                    if (!value) return
                    this.$nextTick(() => {
                        const rect = this.$refs.probClipRect
                        if (!rect) return
                        this.probLineDrawn = true
                        setTimeout(() => {
                            const start = performance.now()
                            const duration = 1200
                            const step = (now) => {
                                const progress = Math.min(1, (now - start) / duration)
                                const eased = 1 - Math.pow(1 - progress, 3)
                                rect.setAttribute('width', String(eased * 280))
                                if (progress < 1) {
                                    requestAnimationFrame(step)
                                }
                            }
                            requestAnimationFrame(step)
                        }, 150)
                    })
                },
            },
            methods: {
                startProgressMotion() {
                    if (this.progressMotionActive) return
                    this.progressMotionActive = true
                    const step = () => {
                        const real = this.analysisProgress?.percent
                        if (typeof real !== 'number' && !this.analysisPolling) {
                            this.progressMotionActive = false
                            this.progressAnimFrame = null
                            return
                        }
                        const mapped = this.mappedProgressPercent
                        const ceiling = this.progressPhaseCeiling
                        // 全程匀速平推：目标取真实进度映射与“当前位置+基础步进”的较大者，
                        // 阶段边界不会减速；落后真实进度较多时再快速追赶
                        const cruise = 0.03
                        const target = Math.min(
                            ceiling,
                            Math.max(mapped, this.displayProgress + cruise),
                        )
                        const delta = target - this.displayProgress
                        if (delta > 0) {
                            const gapToMapped = Math.max(0, mapped - this.displayProgress)
                            const velocity = real >= 100
                                ? 0.35
                                : (gapToMapped > 3
                                    ? 0.3
                                    : Math.max(0.03, Math.min(0.3, delta * 0.05)))
                            this.displayProgress = Math.min(
                                target,
                                this.displayProgress + Math.min(velocity, delta),
                            )
                        } else if (target >= 100) {
                            this.displayProgress = 100
                        }
                        this.progressAnimFrame = requestAnimationFrame(step)
                    }
                    this.progressAnimFrame = requestAnimationFrame(step)
                },
                switchRightView(view) {
                    this.activeRightView = view
                    this.persistWorkspaceState()
                    if (view === 'tasks') {
                        this.volumeViewerExpanded = false
                        // 每次进入任务管理都刷新，避免完成新任务后列表仍是旧数据
                        if (!this.taskHistoryLoading) {
                            this.loadTaskHistory()
                        }
                    } else if (
                        this.selectedFileType === 'volume'
                        && this.volumeViewer
                    ) {
                        this.$nextTick(() => {
                            this.volumeViewer?.drawScene?.()
                        })
                    }
                },
                updateResultSplitViewport() {
                    this.resultSplitViewportWidth = this.$refs.rightContent?.clientWidth || 0
                    this.scheduleResultViewerResize()
                },
                startResultSplitResize(event) {
                    if (event.pointerType === 'mouse' && event.button !== 0) return
                    this.updateResultSplitViewport()
                    if (this.resultSplitViewportWidth < 776) return
                    event.preventDefault()
                    this.resultSplitDragging = true
                    document.body.classList.add('btir-result-split-dragging')
                    this._resultSplitPointerMove = moveEvent => this.updateResultSplitFromPointer(moveEvent)
                    this._resultSplitPointerUp = () => this.stopResultSplitResize()
                    window.addEventListener('pointermove', this._resultSplitPointerMove)
                    window.addEventListener('pointerup', this._resultSplitPointerUp, { once: true })
                    window.addEventListener('pointercancel', this._resultSplitPointerUp, { once: true })
                    this.updateResultSplitFromPointer(event)
                },
                updateResultSplitFromPointer(event) {
                    if (!this.resultSplitDragging) return
                    const container = this.$refs.rightContent
                    if (!container) return
                    const rect = container.getBoundingClientRect()
                    const availableWidth = rect.width - 16
                    if (availableWidth < 760) return
                    const dataWidth = Math.min(
                        availableWidth - 360,
                        Math.max(360, event.clientX - rect.left),
                    )
                    this.resultSplitViewportWidth = rect.width
                    this.resultSplitRatio = dataWidth / availableWidth
                    this.scheduleResultViewerResize()
                },
                stopResultSplitResize() {
                    const wasDragging = this.resultSplitDragging
                    this.resultSplitDragging = false
                    document.body.classList.remove('btir-result-split-dragging')
                    window.removeEventListener('pointermove', this._resultSplitPointerMove)
                    window.removeEventListener('pointerup', this._resultSplitPointerUp)
                    window.removeEventListener('pointercancel', this._resultSplitPointerUp)
                    this._resultSplitPointerMove = null
                    this._resultSplitPointerUp = null
                    if (wasDragging) {
                        try {
                            localStorage.setItem('btir_result_split_ratio', this.resultSplitRatio.toFixed(4))
                        } catch {}
                    }
                },
                setResultSplitRatio(ratio) {
                    this.resultSplitRatio = Math.max(0.4, Math.min(0.68, ratio))
                    try {
                        localStorage.setItem('btir_result_split_ratio', this.resultSplitRatio.toFixed(4))
                    } catch {}
                    this.scheduleResultViewerResize()
                },
                nudgeResultSplit(amount) {
                    this.setResultSplitRatio(this.resultSplitRatio + amount)
                },
                resetResultSplit() {
                    this.setResultSplitRatio(0.618)
                    try {
                        localStorage.removeItem('btir_result_split_ratio')
                    } catch {}
                },
                scheduleResultViewerResize() {
                    if (this.resultSplitDrawFrame !== null) return
                    this.resultSplitDrawFrame = requestAnimationFrame(() => {
                        this.resultSplitDrawFrame = null
                        this.volumeViewer?.drawScene?.()
                    })
                },
                switchViewerPane(pane) {
                    if (!['3d', 'json'].includes(pane) || pane === this.viewerPane) {
                        return
                    }
                    this.viewerPane = pane
                    if (pane === 'json') {
                        this.volumeViewerExpanded = false
                    }
                    this.$nextTick(() => {
                        if (pane === '3d') {
                            this.volumeViewer?.drawScene?.()
                        }
                    })
                },
                persistWorkspaceState() {
                    const serialized = JSON.stringify({
                        taskId: this.taskId || '',
                        view: this.activeRightView,
                    })
                    sessionStorage.setItem('btir_workspace', serialized)
                    localStorage.setItem('btir_workspace', serialized)
                    const url = new URL(window.location.href)
                    if (this.taskId) {
                        url.searchParams.set('task', this.taskId)
                    } else {
                        url.searchParams.delete('task')
                    }
                    if (this.activeRightView === 'tasks') {
                        url.searchParams.set('view', 'tasks')
                    } else {
                        url.searchParams.delete('view')
                    }
                    window.history.replaceState(null, '', url)
                },
                clearWorkspaceState() {
                    sessionStorage.removeItem('btir_workspace')
                    localStorage.removeItem('btir_workspace')
                    const url = new URL(window.location.href)
                    url.searchParams.delete('task')
                    url.searchParams.delete('view')
                    window.history.replaceState(null, '', url)
                },
                finishWorkspaceRestore() {
                    this.workspaceRestoring = false
                    document.documentElement.classList.remove('btir-workspace-restoring')
                },
                async restoreWorkspaceState() {
                    let savedWorkspace = null
                    try {
                        const url = new URL(window.location.href)
                        const taskIdFromUrl = url.searchParams.get('task')
                        const viewFromUrl = url.searchParams.get('view')
                        savedWorkspace = taskIdFromUrl || viewFromUrl
                            ? { taskId: taskIdFromUrl || '', view: viewFromUrl }
                            : JSON.parse(
                                sessionStorage.getItem('btir_workspace')
                                || localStorage.getItem('btir_workspace')
                                || 'null',
                            )
                    } catch {
                        this.clearWorkspaceState()
                    }
                    if (!savedWorkspace) {
                        this.finishWorkspaceRestore()
                        return
                    }

                    if (!savedWorkspace.taskId) {
                        if (savedWorkspace.view === 'tasks') {
                            this.activeRightView = 'tasks'
                            await this.loadTaskHistory()
                        }
                        this.finishWorkspaceRestore()
                        return
                    }

                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(savedWorkspace.taskId)}`,
                            { headers: this.authHeaders },
                        )
                        if (!response.ok) {
                            if (savedWorkspace.view === 'tasks') {
                                this.activeRightView = 'tasks'
                                await this.loadTaskHistory()
                            } else {
                                this.clearWorkspaceState()
                            }
                            return
                        }
                        this.presentTaskResult(await response.json())
                        if (savedWorkspace.view === 'tasks') {
                            this.switchRightView('tasks')
                        }
                    } catch {
                        if (savedWorkspace?.view === 'tasks') {
                            this.activeRightView = 'tasks'
                            await this.loadTaskHistory()
                        } else {
                            this.clearWorkspaceState()
                        }
                    } finally {
                        this.finishWorkspaceRestore()
                    }
                },
                switchTaskList(mode) {
                    if (this.taskListMode === mode) return
                    this.taskListMode = mode
                    this.taskOffset = 0
                    this.loadTaskHistory()
                },
                taskStatusLabel(status) {
                    const labels = {
                        created: '待运行',
                        queued: '排队中',
                        running: '运行中',
                        cancel_requested: '取消中',
                        partial: '部分完成',
                        succeeded: '已完成',
                        failed: '失败',
                        canceled: '已取消',
                    }
                    return labels[status] || status
                },
                canArchiveTask(status) {
                    return ['created', 'partial', 'succeeded', 'failed', 'canceled'].includes(status)
                },
                canCancelTask(status) {
                    return ['created', 'queued', 'running'].includes(status)
                },
                modelNameLabel(model) {
                    const labels = {
                        classification: '分类',
                        segmentation: '分割',
                    }
                    return labels[model] || model
                },
                formatTaskTime(value) {
                    if (!value) return '未知'
                    const date = new Date(value)
                    return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
                },
                formatVolume(value) {
                    const number = Number(value)
                    return Number.isFinite(number)
                        ? number.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
                        : '0'
                },
                compositeDisplayName(key) {
                    return {
                        WT: '全病灶',
                        TC: '肿瘤核心',
                        ET: '强化区域',
                    }[key] || key
                },
                regionBarWidth(region) {
                    const max = Math.max(...this.regionStats.map(item => item.volumeMm3), 0)
                    if (!max) return '0%'
                    const ratio = Math.max(0, Math.min(1, region.volumeMm3 / max))
                    return `${Math.max(3, ratio * 100).toFixed(1)}%`
                },
                compositeBarWidth(key) {
                    const max = Math.max(
                        ...['WT', 'TC', 'ET'].map(
                            k => this.tumorComposites[k]?.volume_mm3 || 0,
                        ),
                        0,
                    )
                    if (!max) return '0%'
                    const ratio = Math.max(
                        0,
                        Math.min(1, (this.tumorComposites[key]?.volume_mm3 || 0) / max),
                    )
                    return `${Math.max(3, ratio * 100).toFixed(1)}%`
                },
                showChartPoint(point, event) {
                    const node = event.currentTarget
                    const wrap = node.parentElement
                    const nodeRect = node.getBoundingClientRect()
                    const wrapRect = wrap.getBoundingClientRect()
                    const xPx = nodeRect.left + nodeRect.width / 2 - wrapRect.left
                    const yPx = nodeRect.top + nodeRect.height / 2 - wrapRect.top
                    this.chartHover = {
                        sliceIndex: point.sliceIndex,
                        probabilityText: `${Math.round(point.probability * 1000) / 10}%`,
                        xPx,
                        yPx,
                        below: yPx < 28,
                    }
                    this.chartHoverVisible = true
                },
                formatInferenceTime(value) {
                    if (value === null || value === undefined || value === '') return '未记录'
                    const milliseconds = Number(value)
                    if (!Number.isFinite(milliseconds)) return '未记录'
                    if (milliseconds < 1000) {
                        return `${milliseconds.toLocaleString('zh-CN', {
                            maximumFractionDigits: 1,
                        })} ms`
                    }
                    return `${(milliseconds / 1000).toLocaleString('zh-CN', {
                        maximumFractionDigits: 2,
                    })} s`
                },
                taskInputSummary(task) {
                    if (task.input?.files) {
                        const count = Object.keys(task.input.files).length
                        return `${count} 个 NIfTI（FLAIR / T1CE / T1 / T2）`
                    }
                    return task.input?.filename || '未知'
                },
                async responseError(response, action) {
                    let detail = ''
                    try {
                        const payload = await response.json()
                        if (typeof payload.detail === 'string') {
                            detail = payload.detail
                        } else if (Array.isArray(payload.detail) && typeof payload.detail[0]?.msg === 'string') {
                            detail = payload.detail[0].msg.replace(/^Value error,\s*/, '')
                        } else {
                            detail = payload.message || ''
                        }
                    } catch {
                    }
                    return detail
                        ? `${action}失败：${detail}`
                        : `${action}失败：HTTP ${response.status}`
                },
                async loadTaskHistory(clearMessage = true) {
                    const requestId = ++this.taskHistoryRequestId
                    this.closeTaskRunHistory()
                    this.taskHistoryLoading = true
                    if (clearMessage) {
                        this.taskMessage = ''
                        this.taskMessageIsError = false
                    }
                    try {
                        const params = new URLSearchParams({
                            limit: String(this.taskLimit),
                            offset: String(this.taskOffset),
                        })
                        if (this.taskQuery) params.set('q', this.taskQuery)
                        if (this.taskStatusFilter) params.set('status', this.taskStatusFilter)

                        const endpoint = this.taskListMode === 'archived'
                            ? '/tasks/archived'
                            : '/tasks'
                        const response = await fetch(`${this.API_BASE}${endpoint}?${params}`, {
                            headers: this.authHeaders,
                        })
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '查询任务'))
                        }
                        const payload = await response.json()
                        if (requestId !== this.taskHistoryRequestId) return
                        this.taskItems = Array.isArray(payload.items) ? payload.items : []
                        this.taskTotal = Number(payload.total) || 0
                    } catch (error) {
                        if (requestId !== this.taskHistoryRequestId) return
                        this.taskItems = []
                        this.taskTotal = 0
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        if (requestId !== this.taskHistoryRequestId) return
                        this.taskHistoryLoading = false
                        this.$nextTick(() => this.initRevealObserver())
                    }
                },
                searchTasks() {
                    this.taskOffset = 0
                    this.loadTaskHistory()
                },
                changeTaskPage(direction) {
                    const nextOffset = this.taskOffset + direction * this.taskLimit
                    if (nextOffset < 0 || nextOffset >= this.taskTotal) return
                    this.taskOffset = nextOffset
                    this.loadTaskHistory()
                },
                closeTaskRunHistory() {
                    this.taskRunHistoryTaskId = ''
                    this.taskRunHistoryItems = []
                    this.taskRunHistoryLoading = false
                },
                startTaskRename(task) {
                    this.taskRenameTaskId = task.task_id
                    this.taskRenameDraft = task.name || ''
                    this.taskMessage = ''
                    this.$nextTick(() => {
                        const input = this.$refs[`task-rename-${task.task_id}`]?.[0]
                        input?.focus()
                        input?.select()
                    })
                },
                cancelTaskRename(task) {
                    if (this.taskRenameTaskId === task.task_id) {
                        this.taskRenameTaskId = ''
                        this.taskRenameDraft = ''
                    }
                },
                onTaskRenameBlur(task, event) {
                    const related = event?.relatedTarget
                    if (
                        related
                        && (
                            related.classList.contains('task-rename-confirm-btn')
                            || related.classList.contains('task-rename-cancel-btn')
                        )
                    ) {
                        return
                    }
                    this.cancelTaskRename(task)
                },
                async saveTaskRename(task) {
                    if (this.taskRenameTaskId !== task.task_id) return
                    const name = (this.taskRenameDraft || '').trim()
                    if (!name || name === task.name) {
                        this.cancelTaskRename(task)
                        return
                    }
                    this.taskRenameTaskId = ''
                    this.taskRenameDraft = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(task.task_id)}/rename`,
                            {
                                method: 'PATCH',
                                headers: {
                                    'Content-Type': 'application/json',
                                    ...this.authHeaders,
                                },
                                body: JSON.stringify({ name }),
                            }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '重命名任务'))
                        }
                        const updated = await response.json()
                        task.name = updated.name || name
                        if (task.case_id) {
                            for (const item of this.taskItems) {
                                if (item.case_id === task.case_id) {
                                    item.case_name = name
                                }
                            }
                        }
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    }
                },
                async toggleTaskRunHistory(task) {
                    const taskId = task.task_id
                    if (this.taskRunHistoryTaskId === taskId) {
                        this.closeTaskRunHistory()
                        return
                    }

                    this.taskRunHistoryTaskId = taskId
                    this.taskRunHistoryItems = []
                    this.taskRunHistoryLoading = true
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(taskId)}/runs?limit=20&offset=0`,
                            { headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '读取运行记录'))
                        }
                        const payload = await response.json()
                        this.taskRunHistoryItems = Array.isArray(payload.items) ? payload.items : []
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                        this.closeTaskRunHistory()
                    } finally {
                        this.taskRunHistoryLoading = false
                    }
                },
                async viewTaskResult(task) {
                    this.taskActionId = task.task_id
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(task.task_id)}`,
                            { headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '读取任务结果'))
                        }
                        this.presentTaskResult(await response.json())
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        this.taskActionId = ''
                    }
                },
                async archiveTask(task) {
                    if (!this.canArchiveTask(task.status)) return
                    if (!window.confirm(`确认归档任务 ${task.task_id}？归档宽限期内可恢复。`)) return

                    this.taskActionId = task.task_id
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(task.task_id)}`,
                            { method: 'DELETE', headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '归档任务'))
                        }
                        const payload = await response.json()
                        this.taskMessage = `任务 ${payload.task_id} 已移入归档列表。`
                        this.taskMessageIsError = false
                        if (this.taskItems.length === 1 && this.taskOffset > 0) {
                            this.taskOffset = Math.max(0, this.taskOffset - this.taskLimit)
                        }
                        await this.loadTaskHistory(false)
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        this.taskActionId = ''
                    }
                },
                async restoreArchivedTask(task) {
                    const taskId = task.task_id
                    this.taskActionId = taskId
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(taskId)}/restore`,
                            { method: 'POST', headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '恢复任务'))
                        }
                        const payload = await response.json()
                        this.taskMessage = `任务已恢复，当前状态：${this.taskStatusLabel(payload.task_status)}。`
                        this.taskMessageIsError = false
                        if (this.taskItems.length === 1 && this.taskOffset > 0) {
                            this.taskOffset = Math.max(0, this.taskOffset - this.taskLimit)
                        }
                        await this.loadTaskHistory(false)
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        this.taskActionId = ''
                    }
                },
                async purgeArchivedTask(task) {
                    const taskId = task.task_id
                    if (!window.confirm(`确认彻底删除任务 ${taskId}？此操作无法恢复。`)) return

                    this.taskActionId = taskId
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(taskId)}/purge`,
                            { method: 'DELETE', headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '彻底删除任务'))
                        }
                        this.taskMessage = `任务 ${taskId} 已彻底删除。`
                        this.taskMessageIsError = false
                        if (this.taskItems.length === 1 && this.taskOffset > 0) {
                            this.taskOffset = Math.max(0, this.taskOffset - this.taskLimit)
                        }
                        await this.loadTaskHistory(false)
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        this.taskActionId = ''
                    }
                },
                async retryTask(task) {
                    if (task.status !== 'failed') return

                    this.taskActionId = task.task_id
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(task.task_id)}/retry`,
                            { method: 'POST', headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '重试任务'))
                        }
                        this.taskMessage = `任务 ${task.task_id} 已重新进入推理队列。`
                        this.taskMessageIsError = false
                        await this.loadTaskHistory(false)
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        this.taskActionId = ''
                    }
                },
                async cancelTask(task) {
                    if (!this.canCancelTask(task.status)) return
                    if (!window.confirm(`确认取消任务 ${task.task_id}？`)) return

                    this.taskActionId = task.task_id
                    this.taskMessage = ''
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(task.task_id)}/cancel`,
                            { method: 'POST', headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            throw new Error(await this.responseError(response, '取消任务'))
                        }
                        const payload = await response.json()
                        this.taskMessage = payload.status === 'cancel_requested'
                            ? `任务 ${task.task_id} 已请求取消。`
                            : `任务 ${task.task_id} 已取消。`
                        this.taskMessageIsError = false
                        await this.loadTaskHistory(false)
                    } catch (error) {
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
                        this.taskActionId = ''
                    }
                },
                escapeHtml(value) {
                    return String(value)
                        .replace(/&/g, '&amp;')
                        .replace(/</g, '&lt;')
                        .replace(/>/g, '&gt;')
                },
                resetState() {
                    this.destroyVolumeViewer()
                    this.loading = true
                    this.analysisActive = true
                    this.displayProgress = 0
                    this.analysisCancelled = false
                    this.analysisPolling = false
                    this.analysisProgress = {
                        percent: 0,
                        stage: '正在压缩/上传数据...',
                    }
                    this.statusText = '<span class="loading-spinner"></span>创建任务中...'
                    this.taskId = ''
                    this.fileList = []
                    this.downloadFiles = []
                    this.selectedFilePath = ''
                    this.selectedFileType = ''
                    this.integratedSources = []
                    this.viewerPane = '3d'
                    this.volumeViewerSources = null
                    this.volumeViewerError = ''
                    this.volumeViewerLoading = false
                    this.classificationLabel = ''
                    this.confidence = 0
                    this.tumorArea = null
                    this.regionStats = []
                    this.tumorComposites = {}
                    this.tumorMorphology = {}
                    this.tumorSpatial = {}
                    this.classProbabilities = {}
                    this.caseInputFiles = {}
                    this.clearCasePreview()
                    this.probabilitySeries = []
                    this.probabilityThreshold = 0.548381
                    this.chartHover = null
                    this.chartHoverVisible = false
                    this.modelConsensus = null
                    this.supplementaryAnalysis = null
                },
                startNewUpload() {
                    this.resetState()
                    this.activeRightView = 'results'
                    this.clearWorkspaceState()
                    this.loading = false
                    this.analysisActive = false
                    this.analysisProgress = null
                    this.statusText = '等待识别...'
                    this.volumeFiles = { flair: null, t1ce: null, t1: null, t2: null }
                    this.volumeArchiveFile = null
                    this.volumeDicomFiles = []
                    this.volumeFolderLabel = ''
                    this.caseId = ''
                    this.caseName = ''
                    this.studyDate = new Date().toISOString().slice(0, 10)
                    this.volumeManualMode = false
                    this.volumeDropActive = false
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    this.dicomSeriesCandidates = {}
                    this.dicomSeriesSelections = {}
                    this.clearVolumeSelectionState()
                    this.$nextTick(() => {
                        this.initRevealObserver()
                        this.$refs.volumeDropZone?.scrollIntoView({ behavior: 'smooth', block: 'start' })
                    })
                },
                openSampleGuide() {
                    window.location.href = 'guide.html'
                },
                openAbout() {
                    window.location.href = 'about.html'
                },
                handleHomeClick() {
                    if (this.taskId) {
                        this.startNewUpload()
                    } else {
                        this.openAbout()
                    }
                },
                startFollowUpUpload(task = null) {
                    const caseId = task?.case_id || this.caseId || task?.task_id || this.taskId
                    const caseName = task?.case_name || this.caseName || task?.name || '当前病例'
                    if (!caseId) return
                    this.startNewUpload()
                    this.caseId = caseId
                    this.caseName = caseName
                    this.followUpContextDismissed = false
                },
                dismissFollowUpContext() {
                    this.followUpContextDismissed = true
                },
                buildFileList(resultData = {}, taskData = null) {
                    const files = []
                    this.integratedSources = []
                    let maskPath = ''
                    const rf = resultData.result_files || null
                    if (rf) {
                        maskPath = rf.mask || maskPath
                    }
                    maskPath = resultData.segmentation?.mask_file || maskPath
                    const inputs = taskData?.input?.files || resultData.input_files || {}
                    const modalities = {}
                    for (const modality of this.volumeModalities) {
                        const entry = inputs[modality.key]
                        const filename = typeof entry === 'string' ? entry : entry?.filename
                        if (filename) {
                            modalities[modality.key] = {
                                path: `input/${filename}`,
                                name: filename,
                            }
                        }
                    }

                    const jsonFiles = []
                    if (rf && rf.frontend) {
                        jsonFiles.push({ label: 'frontend_result.json', path: rf.frontend })
                    }
                    if (jsonFiles.length) {
                        this.integratedSources = jsonFiles
                        files.push({
                            label: '病例概览',
                            path: '@integrated',
                            type: 'integrated',
                            sources: { files: jsonFiles },
                        })
                    }

                    if (Object.keys(modalities).length) {
                        files.push({
                            label: '3D视图',
                            path: '@volume-viewer',
                            type: 'volume',
                            sources: {
                                modalities,
                                mask: maskPath
                                    ? {
                                        path: maskPath,
                                        name: maskPath.split('/').pop(),
                                    }
                                    : null,
                            },
                        })
                    }

                    const downloads = []
                    const addDownload = (label, path) => {
                        if (!path || downloads.some(entry => entry.path === path)) {
                            return
                        }
                        downloads.push({ label, path, type: 'download' })
                    }
                    for (const modality of this.volumeModalities) {
                        const source = modalities[modality.key]
                        if (source) {
                            addDownload(source.name, source.path)
                        }
                    }
                    addDownload(maskPath.split('/').pop() || '3D分割掩码', maskPath)
                    this.downloadFiles = downloads
                    return files
                },
                taskFileUrl(filePath) {
                    const taskId = encodeURIComponent(this.taskId)
                    const path = filePath.split('/').map(encodeURIComponent).join('/')
                    return `${this.API_BASE}/tasks/${taskId}/files/${path}`
                },
                formatFollowUpChange(change, percent, unit) {
                    const sign = change > 0 ? '+' : ''
                    const precision = unit === 'probability' ? 1 : 0
                    const amount = unit === 'probability'
                        ? `${sign}${(change * 100).toFixed(precision)} 个百分点`
                        : `${sign}${this.formatVolume(change)} ${unit === 'area' ? 'mm²' : 'mm³'}`
                    if (percent === null || !Number.isFinite(percent)) return amount
                    return `${amount} · ${sign}${percent.toFixed(1)}%`
                },
                followUpChangeTone(change) {
                    if (Math.abs(change) < 0.000001) return 'stable'
                    return change > 0 ? 'increase' : 'decrease'
                },
                selectFollowUpComparison(taskId) {
                    this.selectedFollowUpTaskId = taskId
                },
                async loadFollowUpComparison() {
                    const taskId = this.taskId
                    if (!taskId) return
                    try {
                        const followUpResponse = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(taskId)}/follow-up`,
                            { headers: this.authHeaders },
                        )
                        if (!followUpResponse.ok) {
                            throw new Error(await this.responseError(followUpResponse, '读取随访数据'))
                        }
                        const payload = await followUpResponse.json()
                        if (taskId === this.taskId) {
                            const history = Array.isArray(payload.history) ? payload.history : []
                            this.followUp = payload.baseline || history.length ? payload : null
                            this.selectedFollowUpTaskId = payload.baseline?.task_id || history[0]?.task?.task_id || ''
                            this.$nextTick(() => this.initRevealObserver())
                        }
                    } catch {
                        if (taskId === this.taskId) {
                            this.followUp = null
                            this.selectedFollowUpTaskId = ''
                        }
                    }
                },
                clearCasePreview() {
                    this.closeCasePreviewFullscreen()
                    this.casePreviewRequestId += 1
                    const previewUrls = new Set([
                        this.casePreviewUrl,
                        ...Object.values(this.casePreviewUrls),
                    ])
                    for (const url of previewUrls) {
                        if (url) URL.revokeObjectURL(url)
                    }
                    this.casePreviewPath = ''
                    this.casePreviewUrl = ''
                    this.casePreviewFrames = []
                    this.casePreviewUrls = {}
                    this.casePreviewMode = 'overlay'
                    this.casePreviewActiveIndex = 0
                    this.casePreviewDirection = 1
                },
                async loadCasePreview(series, fallbackPath = '') {
                    this.clearCasePreview()
                    if (!this.taskId) return

                    const frames = Array.isArray(series?.frames)
                        ? series.frames.map(frame => ({
                            sliceIndex: Number.isInteger(frame?.slice_index)
                                ? frame.slice_index
                                : null,
                            offset: Number.isInteger(frame?.offset) ? frame.offset : 0,
                            raw: typeof frame?.raw === 'string' ? frame.raw : '',
                            overlay: typeof frame?.overlay === 'string' ? frame.overlay : '',
                        })).filter(frame => frame.raw || frame.overlay)
                        : []
                    if (!frames.length && fallbackPath) {
                        frames.push({
                            sliceIndex: null,
                            offset: 0,
                            raw: '',
                            overlay: fallbackPath,
                        })
                    }
                    if (!frames.length) return

                    this.casePreviewFrames = frames
                    const focusIndex = frames.findIndex(frame => frame.offset === 0)
                    this.casePreviewActiveIndex = focusIndex >= 0 ? focusIndex : 0
                    await this.loadActiveCasePreview()
                },
                async loadActiveCasePreview() {
                    const filePath = this.activeCasePreviewPath
                    if (!filePath || !this.taskId) return

                    this.casePreviewPath = filePath
                    const cached = this.casePreviewUrls[filePath]
                    if (cached) {
                        this.casePreviewUrl = cached
                        return
                    }

                    this.casePreviewUrl = ''
                    const requestId = ++this.casePreviewRequestId
                    const requestTaskId = this.taskId

                    try {
                        const response = await fetch(this.taskFileUrl(filePath), {
                            headers: this.authHeaders,
                        })
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}`)
                        }
                        const previewUrl = URL.createObjectURL(await response.blob())
                        if (
                            requestTaskId !== this.taskId
                            || requestId !== this.casePreviewRequestId
                            || filePath !== this.activeCasePreviewPath
                        ) {
                            URL.revokeObjectURL(previewUrl)
                            return
                        }
                        this.casePreviewUrls = {
                            ...this.casePreviewUrls,
                            [filePath]: previewUrl,
                        }
                        this.casePreviewUrl = previewUrl
                    } catch {
                        if (requestId === this.casePreviewRequestId) {
                            this.casePreviewUrl = ''
                        }
                    }
                },
                setCasePreviewMode(mode) {
                    if (mode !== 'overlay' && mode !== 'raw') return
                    if (mode === 'raw' && !this.casePreviewHasRaw) return
                    if (this.casePreviewMode === mode && this.casePreviewUrl) return
                    this.casePreviewDirection = 1
                    this.casePreviewMode = mode
                    void this.loadActiveCasePreview()
                },
                selectCasePreviewFrame(index) {
                    if (index < 0 || index >= this.casePreviewFrames.length) return
                    if (index === this.casePreviewActiveIndex && this.casePreviewUrl) return
                    this.casePreviewDirection = index > this.casePreviewActiveIndex ? 1 : -1
                    this.casePreviewActiveIndex = index
                    void this.loadActiveCasePreview()
                },
                openCasePreviewFullscreen() {
                    if (!this.casePreviewUrl) return
                    this.casePreviewFullscreen = true
                    document.body.classList.add('btir-preview-fullscreen-open')
                    this.$nextTick(() => this.$refs.casePreviewFullscreenClose?.focus())
                },
                closeCasePreviewFullscreen() {
                    this.casePreviewFullscreen = false
                    document.body.classList.remove('btir-preview-fullscreen-open')
                },
                handleCasePreviewKeydown(event) {
                    if (event.key === 'Escape' && this.casePreviewFullscreen) {
                        this.closeCasePreviewFullscreen()
                    }
                },
                playResultAnimations() {
                    this.ringRevealed = false
                    this.segRingRevealed = false
                    this.probLineRevealed = false
                    this.probLineDrawn = false
                    this.$nextTick(() => {
                        requestAnimationFrame(() => {
                            this.ringRevealed = Boolean(this.classificationLabel)
                            this.segRingRevealed = this.tumorArea !== null
                            this.probLineRevealed = this.probabilitySeries.length >= 2
                        })
                    })
                },
                cancelDeferredVolumeLoad() {
                    if (this.deferredVolumeLoadTimer !== null) {
                        clearTimeout(this.deferredVolumeLoadTimer)
                        this.deferredVolumeLoadTimer = null
                    }
                },
                deferCaseVolumeViewer() {
                    this.cancelDeferredVolumeLoad()
                    this.deferredVolumeLoadTimer = setTimeout(() => {
                        this.deferredVolumeLoadTimer = null
                        void this.openCaseVolumeViewer()
                    }, 1500)
                },
                async openCaseVolumeViewer() {
                    this.cancelDeferredVolumeLoad()
                    const volumeEntry = this.fileList.find(file => file.type === 'volume')
                    if (!volumeEntry?.sources?.modalities) return
                    await this.openVolumeViewer(volumeEntry)
                },
                toggleVolumeViewerExpanded() {
                    this.volumeViewerExpanded = !this.volumeViewerExpanded
                    this.$nextTick(() => {
                        this.volumeViewer?.drawScene?.()
                    })
                },
                returnToCaseOverview() {
                    this.$refs.caseDataColumn?.scrollTo({ top: 0, behavior: 'smooth' })
                },
                async openVolumeViewer(file) {
                    if (!file.sources?.modalities) return
                    if (
                        this.selectedFileType === 'volume'
                        && this.selectedFilePath === file.path
                        && this.volumeViewer
                        && !this.volumeViewerError
                    ) {
                        return
                    }

                    this.destroyVolumeViewer()
                    this.selectedFilePath = file.path
                    this.selectedFileType = 'volume'
                    this.volumeViewerSources = file.sources
                    this.volumeViewerError = ''
                    this.volumeViewerLoading = true

                    const modalities = file.sources.modalities
                    if (!modalities[this.selectedVolumeModality]) {
                        this.selectedVolumeModality = this.volumeModalities.find(
                            modality => modalities[modality.key]
                        )?.key || ''
                    }
                    await this.$nextTick()
                    // 先让浏览器绘制“正在加载”界面，再启动 NiiVue 初始化与数据下载，
                    // 避免初始化期间的同步阻塞让页面看起来像卡住
                    await new Promise((resolve) => {
                        requestAnimationFrame(() => requestAnimationFrame(resolve))
                    })
                    await this.loadSelectedVolume()
                },
                async waitForVolumeCanvas() {
                    for (let attempt = 0; attempt < 12; attempt += 1) {
                        await this.$nextTick()
                        await new Promise(resolve => requestAnimationFrame(resolve))
                        const canvas = this.$refs.volumeCanvas
                        if (
                            canvas?.isConnected
                            && canvas.clientWidth > 16
                            && canvas.clientHeight > 16
                        ) {
                            return canvas
                        }
                    }
                    return this.$refs.volumeCanvas || null
                },
                async loadSelectedVolume() {
                    const sources = this.volumeViewerSources
                    const base = sources?.modalities?.[this.selectedVolumeModality]
                    const canvas = await this.waitForVolumeCanvas()
                    if (!sources || !base || !canvas) {
                        this.volumeViewerError = '3D 查看器未完成初始化，请重新展开 3D 查看'
                        return
                    }

                    this.volumeViewerLoading = true
                    this.volumeViewerError = ''
                    this.volumeDownload = null
                    try {
                        if (!this.volumeViewer) {
                            this.volumeViewer = Vue.markRaw(
                                new window.BtirVolumeViewer(canvas)
                            )
                        }
                        await this.volumeViewer.load({
                            base: {
                                url: this.taskFileUrl(base.path),
                                name: base.name,
                            },
                            mask: sources.mask
                                ? {
                                    url: this.taskFileUrl(sources.mask.path),
                                    name: sources.mask.name,
                                }
                                : null,
                            headers: this.authHeaders,
                            maskOpacity: this.volumeMaskOpacity,
                            maskVisible: this.volumeMaskVisible,
                            viewMode: this.volumeViewMode,
                            onProgress: (progress) => {
                                this.volumeDownload = progress
                            },
                        })
                    } catch (error) {
                        if (error.name !== 'AbortError') {
                            this.volumeViewerError = `3D 数据读取失败：${error.message}`
                        }
                    } finally {
                        this.volumeViewerLoading = false
                        this.volumeDownload = null
                    }
                },
                async retryVolumeViewer() {
                    const volumeEntry = this.fileList.find(file => file.type === 'volume')
                    if (!volumeEntry) return
                    await this.openVolumeViewer(volumeEntry)
                },
                async changeVolumeModality(modality) {
                    if (
                        this.volumeViewerLoading
                        || modality === this.selectedVolumeModality
                        || !this.volumeViewerSources?.modalities?.[modality]
                    ) {
                        return
                    }
                    this.selectedVolumeModality = modality
                    await this.loadSelectedVolume()
                },
                changeVolumeViewMode(mode) {
                    if (!['multiplanar', 'render'].includes(mode)) return
                    this.volumeViewMode = mode
                    this.volumeViewer?.setViewMode(mode)
                },
                updateVolumeMaskOpacity() {
                    const opacity = this.volumeMaskVisible
                        ? this.volumeMaskOpacity
                        : 0
                    this.volumeViewer?.setMaskOpacity(opacity)
                },
                destroyVolumeViewer() {
                    this.cancelDeferredVolumeLoad()
                    this.volumeViewer?.cleanup()
                    this.volumeViewer = null
                    this.volumeViewerLoading = false
                    this.volumeDownload = null
                    this.volumeViewerExpanded = false
                },
                selectFile(f) {
                    if (f.type === 'volume') {
                        this.openVolumeViewer(f)
                        return
                    }
                    if (f.type === 'integrated') {
                        this.destroyVolumeViewer()
                        this.selectedFilePath = f.path
                        this.selectedFileType = 'integrated'
                        this.playResultAnimations()
                        return
                    }
                },
                async downloadTaskFile(file) {
                    const previousPath = this.selectedFilePath
                    this.selectedFilePath = file.path
                    try {
                        const response = await fetch(this.taskFileUrl(file.path), {
                            headers: this.authHeaders,
                        })
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}`)
                        }
                        const blob = await response.blob()
                        const url = URL.createObjectURL(blob)
                        const anchor = document.createElement('a')
                        anchor.href = url
                        anchor.download = file.path.split('/').pop() || 'btir-result'
                        document.body.appendChild(anchor)
                        anchor.click()
                        document.body.removeChild(anchor)
                        URL.revokeObjectURL(url)
                    } catch (error) {
                        const message = this.escapeHtml(`下载失败：${error.message}`)
                        this.statusText = `<span class="status-error">✗ ${message}</span>`
                    } finally {
                        this.selectedFilePath = previousPath
                    }
                },
                async buildReportPrintLogo(sourceUrl) {
                    try {
                        const response = await fetch(sourceUrl)
                        if (!response.ok) throw new Error(`HTTP ${response.status}`)
                        const sourceBlob = await response.blob()
                        const objectUrl = URL.createObjectURL(sourceBlob)
                        const image = await new Promise((resolve, reject) => {
                            const element = new Image()
                            element.onload = () => {
                                URL.revokeObjectURL(objectUrl)
                                resolve(element)
                            }
                            element.onerror = () => {
                                URL.revokeObjectURL(objectUrl)
                                reject(new Error('Logo 加载失败'))
                            }
                            element.src = objectUrl
                        })
                        const side = 96
                        const canvas = document.createElement('canvas')
                        canvas.width = side
                        canvas.height = side
                        const context = canvas.getContext('2d')
                        context.drawImage(image, 0, 0, side, side)
                        const imageData = context.getImageData(0, 0, side, side)
                        for (let index = 0; index < imageData.data.length; index += 4) {
                            const luminosity = 0.2126 * imageData.data[index]
                                + 0.7152 * imageData.data[index + 1]
                                + 0.0722 * imageData.data[index + 2]
                            const foreground = Math.max(0, Math.min(1, (luminosity - 22) / 160))
                            imageData.data[index] = 29
                            imageData.data[index + 1] = 78
                            imageData.data[index + 2] = 128
                            imageData.data[index + 3] = Math.round(imageData.data[index + 3] * foreground)
                        }
                        context.putImageData(imageData, 0, 0)
                        return canvas.toDataURL('image/png')
                    } catch {
                        return sourceUrl
                    }
                },
                async exportReport() {
                    if (this.exportingReport) return
                    const dataCol = this.$refs.caseDataColumn
                    if (!dataCol) {
                        this.statusText = '<span class="status-error">✗ 未找到报告内容</span>'
                        return
                    }
                    this.exportingReport = true
                    try {
                        const reportTaskId = this.taskId
                        const reportPreviewPaths = this.casePreviewFrames
                            .map(frame => this.casePreviewMode === 'raw' && frame.raw ? frame.raw : frame.overlay)
                            .filter(Boolean)
                        const missingPreviewPaths = [...new Set(reportPreviewPaths.filter(path => !this.casePreviewUrls[path]))]
                        const loadedPreviewEntries = await Promise.all(missingPreviewPaths.map(async (path) => {
                            try {
                                const response = await fetch(this.taskFileUrl(path), { headers: this.authHeaders })
                                if (!response.ok) return [path, '']
                                return [path, URL.createObjectURL(await response.blob())]
                            } catch {
                                return [path, '']
                            }
                        }))
                        if (reportTaskId !== this.taskId) {
                            loadedPreviewEntries.forEach(([, url]) => url && URL.revokeObjectURL(url))
                            return
                        }
                        const loadedPreviewUrls = Object.fromEntries(loadedPreviewEntries.filter(([, url]) => url))
                        if (Object.keys(loadedPreviewUrls).length) {
                            this.casePreviewUrls = { ...this.casePreviewUrls, ...loadedPreviewUrls }
                        }
                        const reportPreviewUrls = { ...this.casePreviewUrls, ...loadedPreviewUrls }
                        const contentClone = dataCol.cloneNode(true)
                        contentClone.querySelectorAll('details').forEach((details) => {
                            const section = document.createElement('section')
                            section.className = `${details.className} btir-report-expanded-section`.trim()
                            for (const child of [...details.children]) {
                                if (child.tagName === 'SUMMARY') {
                                    const heading = document.createElement('div')
                                    heading.className = 'btir-report-section-heading'
                                    heading.textContent = child.textContent.trim()
                                    section.appendChild(heading)
                                } else {
                                    section.appendChild(child)
                                }
                            }
                            details.replaceWith(section)
                        })
                        const reportPreviewFrames = this.casePreviewFrames.map((frame) => {
                            const path = this.casePreviewMode === 'raw' && frame.raw ? frame.raw : frame.overlay
                            return { ...frame, url: reportPreviewUrls[path] || '' }
                        }).filter(frame => frame.url)
                        contentClone.querySelectorAll('.case-preview-figure').forEach((previewFigure) => {
                            if (!reportPreviewFrames.length) return
                            const gallery = document.createElement('section')
                            gallery.className = 'btir-report-preview-gallery'
                            const sourceLabel = this.casePreviewMode === 'raw' ? '四模态原始切片' : '四模态切片与分割叠加'
                            gallery.innerHTML = `<h2>扫描模态图 · ${sourceLabel}</h2><div class="btir-report-preview-grid"></div>`
                            const grid = gallery.querySelector('.btir-report-preview-grid')
                            reportPreviewFrames.forEach((frame) => {
                                const position = frame.offset === 0
                                    ? '最大病灶层'
                                    : (frame.offset < 0 ? '最大病灶层前一层' : '最大病灶层后一层')
                                const caption = Number.isInteger(frame.sliceIndex)
                                    ? `${position} · 切片 ${frame.sliceIndex}`
                                    : position
                                const item = document.createElement('figure')
                                item.innerHTML = `<img src="${frame.url}" alt="${caption}"><figcaption>${caption}</figcaption>`
                                grid.appendChild(item)
                            })
                            previewFigure.replaceWith(gallery)
                        })
                        contentClone.querySelectorAll('.case-preview-open').forEach((preview) => {
                            const image = preview.querySelector('img')
                            if (!image) return
                            const reportPreview = document.createElement('div')
                            reportPreview.className = 'case-preview-open case-preview-report-image'
                            reportPreview.appendChild(image.cloneNode(true))
                            preview.replaceWith(reportPreview)
                        })
                        contentClone.querySelectorAll('button, .case-preview-dots, .file-downloads, .task-manager, .no-print').forEach(n => n.remove())
                        const contentHTML = contentClone.outerHTML
                        const cssBase = new URL('./theme.css', document.baseURI).href
                        const cssApp = new URL('./app.css', document.baseURI).href
                        const logoSrc = new URL('/assets/icon_exp.png', document.baseURI).href
                        const printLogoSrc = await this.buildReportPrintLogo(logoSrc)
                        const caseName = this.escapeHtml(this.caseName || this.caseId || this.taskId || '')
                        const studyDate = this.escapeHtml(this.studyDate || '未登记')
                        const win = window.open('', '_blank', 'width=900,height=720')
                        if (!win) {
                            this.statusText = '<span class="status-error">✗ 弹窗被拦截，请允许本站弹窗后重试</span>'
                            return
                        }
                        win.document.write(`<!DOCTYPE html><html lang="zh-CN" data-theme="light"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>智瞳医脑报告 - ${caseName}</title><link rel="stylesheet" href="${cssBase}"><link rel="stylesheet" href="${cssApp}"><style>@page{margin:12mm;size:A4}html,body{background:#ffffff}body{margin:0;padding:20px;color:#1f2937}.btir-report-page{max-width:210mm;margin:0 auto}.btir-report-actions{position:sticky;top:0;z-index:10;display:flex;justify-content:flex-end;gap:8px;margin:0 0 18px;padding:10px;background:rgba(255,255,255,.94);border-bottom:1px solid #d9e3ef}.btir-report-actions button{min-height:36px;padding:6px 14px;border:1px solid #2563a8;border-radius:6px;background:#ffffff;color:#1d4e80;font:600 13px system-ui,sans-serif;cursor:pointer}.btir-report-actions .btir-report-save{background:#2563a8;color:#ffffff}.btir-report-header{margin:0 0 20px;padding:0 0 16px;border-bottom:2px solid #2563a8}.btir-report-header h1{margin:0;color:#1d4e80;font-size:24px}.btir-report-header p{margin:6px 0 0;color:#475569;font-size:13px}.btir-report-content,.btir-report-content .case-data-column{width:auto!important;min-height:0!important;max-height:none!important;padding:0!important;overflow:visible!important}.btir-report-content .case-viewer-tabs,.btir-report-content .file-downloads{display:none!important}@media print{body{padding:0}.btir-report-actions{display:none!important}.btir-report-page{max-width:none}.btir-report-content [data-reveal]{opacity:1!important;transform:none!important}}</style></head><body><main class="btir-report-page"><div class="btir-report-actions"><button type="button" class="btir-report-save" onclick="window.print()">下载 / 保存 PDF</button><button type="button" onclick="window.close()">关闭预览</button></div><header class="btir-report-header"><h1>智瞳医脑 · 病例分析报告</h1><p>病例：${caseName}　检查日期：${studyDate}</p></header><section class="btir-report-content">${contentHTML}</section></main></body></html>`)
                        win.document.head.insertAdjacentHTML('beforeend', `<style>@page{margin:12mm 12mm 20mm;size:A4}.btir-report-actions button:hover{color:#ffffff;background:#1d4e80;border-color:#1d4e80}.btir-report-actions .btir-report-save:hover{background:#123e6c;border-color:#123e6c}.btir-report-content [data-reveal]{opacity:1!important;transform:none!important}.btir-report-expanded-section{display:block!important}.btir-report-section-heading{margin:12px 0 8px;color:#1d4e80;font-size:13px;font-weight:700}.btir-report-preview-gallery{margin:18px 0 22px;padding:14px;border:1px solid #d9e3ef;border-radius:8px;background:#f8fbff;break-inside:avoid}.btir-report-preview-gallery h2{margin:0 0 12px;color:#1d4e80;font-size:15px}.btir-report-preview-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.btir-report-preview-grid figure{min-width:0;margin:0}.btir-report-preview-grid img{display:block;width:100%;aspect-ratio:1/1;object-fit:contain;background:#02060b;border-radius:5px}.btir-report-preview-grid figcaption{margin-top:6px;color:#475569;font-size:11px;text-align:center}.btir-report-watermark{position:fixed;left:0;bottom:0;z-index:2;display:flex;align-items:center;gap:6px;padding:5px 8px;color:#1d4e80;background:rgba(255,255,255,.88);font:600 10px system-ui,sans-serif;opacity:.82}.btir-report-watermark-logo-screen{display:inline-block;width:18px;height:18px;background:#1d4e80;-webkit-mask:url('${logoSrc}') center/contain no-repeat;mask:url('${logoSrc}') center/contain no-repeat}.btir-report-watermark-logo-print{display:none;width:18px;height:18px;object-fit:contain;-webkit-print-color-adjust:exact;print-color-adjust:exact}@media screen and (max-width:640px){.btir-report-preview-grid{grid-template-columns:1fr}}@media print{.btir-report-watermark{position:static;justify-content:flex-end;margin:12mm 0 0;padding:0;background:transparent;opacity:1}.btir-report-watermark-logo-screen{display:none}.btir-report-watermark-logo-print{display:block}.btir-report-preview-gallery{break-inside:avoid}}</style>`)
                        win.document.body.insertAdjacentHTML('beforeend', `<footer class="btir-report-watermark"><span class="btir-report-watermark-logo-screen" aria-hidden="true"></span><img class="btir-report-watermark-logo-print" src="${printLogoSrc}" alt=""><span>智瞳医脑 · BTIR</span></footer>`)
                        win.document.close()
                        win.focus()
                    } catch (error) {
                        const message = this.escapeHtml(`报告导出失败：${error.message}`)
                        this.statusText = `<span class="status-error">✗ ${message}</span>`
                    } finally {
                        this.exportingReport = false
                    }
                },
                presentTaskResult(taskData) {
                    this.destroyVolumeViewer()
                    this.taskId = taskData.task_id
                    this.caseId = taskData.case_id || taskData.task_id
                    this.caseName = taskData.case_name || taskData.name || '当前病例'
                    this.studyDate = taskData.study_date || this.studyDate
                    const resultData = taskData.frontend_result || {}
                    const status = taskData.status
                    if (status === 'succeeded') {
                        this.statusText = ''
                    } else if (status === 'failed') {
                        this.statusText = '<span class="status-error">✗ 任务失败</span>'
                    } else {
                        this.statusText = `任务状态：${this.escapeHtml(this.taskStatusLabel(status))}`
                    }

                    this.classificationLabel = ''
                    this.confidence = 0
                    this.tumorArea = null
                    this.regionStats = []
                    this.probabilitySeries = []
                    this.probabilityThreshold = 0.548381
                    this.chartHover = null
                    this.chartHoverVisible = false
                    this.ringRevealed = false
                    this.segRingRevealed = false
                    this.probLineRevealed = false
                    this.probLineLength = 0
                    this.probLineDrawn = false
                    this.tumorComposites = {}
                    this.tumorMorphology = {}
                    this.tumorSpatial = {}
                    this.classProbabilities = {}
                    this.caseInputFiles = resultData.input_files || taskData?.input?.files || {}
                    this.followUp = null
                    this.selectedFollowUpTaskId = ''
                    this.clearCasePreview()
                    this.modelConsensus = resultData.model_consensus || null
                    this.supplementaryAnalysis = resultData.supplementary_analysis || null
                    if (resultData.classification) {
                        const classification = resultData.classification
                        this.classificationLabel = classification.class === 'yes'
                            ? '肿瘤 detected'
                            : '正常'
                        this.confidence = classification.confidence
                        this.classProbabilities = classification.probabilities || {}
                        this.probabilitySeries = Array.isArray(
                            classification.slice_probability_series
                        ) ? classification.slice_probability_series : []
                        this.probabilityThreshold = classification.threshold || 0.548381
                    }
                    if (resultData.segmentation) {
                        const regions = resultData.segmentation.regions || {}
                        this.tumorComposites = resultData.segmentation.composites || {}
                        this.tumorMorphology = resultData.segmentation.morphology || {}
                        this.tumorSpatial = resultData.segmentation.spatial || {}
                        const names = { '1': 'NCR/NET', '2': 'ED', '4': 'ET' }
                        this.regionStats = ['1', '2', '4']
                            .filter(label => regions[label])
                            .map(label => ({
                                label,
                                name: names[label],
                                volumeMm3: Number(regions[label].volume_mm3) || 0,
                            }))
                        const ratios = ['1', '2', '4']
                            .map(label => Number(regions[label]?.ratio))
                            .filter(Number.isFinite)
                        if (ratios.length) {
                            this.tumorArea = ratios.reduce((sum, ratio) => sum + ratio, 0)
                        }
                    }
                    const resultFiles = resultData.result_files || {}
                    void this.loadCasePreview(
                        resultFiles.preview_series,
                        resultFiles.preview || '',
                    )

                    this.fileList = this.buildFileList(resultData, taskData)
                    this.selectedFilePath = ''
                    this.selectedFileType = ''
                    this.volumeViewerSources = null
                    this.volumeViewerError = ''
                    this.activeRightView = 'results'
                    this.viewerPane = '3d'
                    const detailEntry = this.fileList.find(file => file.type === 'integrated')
                    if (detailEntry) {
                        this.selectFile(detailEntry)
                    }
                    this.persistWorkspaceState()
                    this.$nextTick(() => {
                        this.initRevealObserver()
                        this.updateResultSplitViewport()
                    })
                    void this.loadFollowUpComparison()
                    this.deferCaseVolumeViewer()
                },
                async runAndGetResult(taskId) {
                    this.analysisCancelled = false
                    this.statusText = '<span class="loading-spinner"></span>运行3D模型中...'

                    const runResponse = await fetch(`${this.API_BASE}/tasks/${taskId}/run-async`, {
                        method: 'POST',
                        headers: this.authHeaders,
                    })

                    if (!runResponse.ok) {
                        throw new Error(await this.responseError(runResponse, '运行模型'))
                    }

                    this.analysisPolling = true
                    this.startProgressMotion()
                    try {
                        const pollingStartedAt = Date.now()
                        const deadline = pollingStartedAt + 30 * 60 * 1000
                        while (Date.now() < deadline) {
                            if (this.analysisCancelled) {
                                this.statusText =
                                    `<span class="status-error">✗ 已取消任务 ${taskId}</span>`
                                return
                            }
                            const resultResponse = await fetch(`${this.API_BASE}/tasks/${taskId}`, {
                                headers: this.authHeaders,
                            })
                            if (!resultResponse.ok) {
                                throw new Error(`获取结果失败: ${resultResponse.status}`)
                            }

                            const resultData = await resultResponse.json()
                            if (resultData.status === 'succeeded') {
                                await this.settleAndPresentResult(resultData)
                                return
                            }
                            if (resultData.status === 'failed') {
                                throw new Error(resultData.error?.message || '识别任务失败')
                            }
                            if (resultData.status === 'canceled') {
                                this.statusText =
                                    `<span class="status-error">✗ 任务 ${taskId} 已取消</span>`
                                return
                            }

                            this.statusText = resultData.status === 'queued'
                                ? '<span class="loading-spinner"></span>任务排队中...'
                                : resultData.status === 'cancel_requested'
                                    ? '<span class="loading-spinner"></span>取消中，正在停止推理...'
                                    : '<span class="loading-spinner"></span>3D分析推理中...'
                            if (
                                resultData.progress !== null
                                && resultData.progress !== undefined
                            ) {
                                this.analysisProgress = {
                                    percent: Math.max(
                                        this.analysisProgress?.percent || 0,
                                        Math.min(
                                            100,
                                            Math.max(
                                                0,
                                                Math.round(
                                                    Number(resultData.progress) || 0
                                                )
                                            )
                                        )
                                    ),
                                    stage: resultData.progress_stage || '',
                                }
                            }
                            const elapsedPollingMs = Date.now() - pollingStartedAt
                            const pollInterval = elapsedPollingMs < 15_000
                                ? 500
                                : (elapsedPollingMs < 60_000 ? 1500 : 3000)
                            await new Promise(resolve => setTimeout(resolve, pollInterval))
                        }

                        throw new Error('识别任务超时，请稍后重试')
                    } finally {
                        this.analysisPolling = false
                        this.analysisProgress = null
                    }
                },
                async settleAndPresentResult(resultData) {
                    this.analysisProgress = {
                        percent: 100,
                        stage: '3D 分割与综合分析完成',
                    }
                    this.statusText = '分析完成，正在呈现结果...'
                    // 等待进度条真正推到 100%（短暂停留后渐隐），最多等 2.5 秒兜底
                    const settleStartedAt = Date.now()
                    const minHoldMs = 400
                    const settleDeadline = settleStartedAt + 2500
                    while (
                        Date.now() < settleDeadline
                        && (
                            this.displayProgress < 99.5
                            || Date.now() - settleStartedAt < minHoldMs
                        )
                    ) {
                        await new Promise(resolve => setTimeout(resolve, 50))
                    }
                    this.statusText = ''
                    this.analysisProgress = null
                    this.analysisPolling = false
                    await new Promise(resolve => setTimeout(resolve, 350))
                    this.presentTaskResult(resultData)
                },
                async cancelCurrentAnalysis() {
                    if (!this.taskId || this.analysisCancelled) return
                    this.analysisCancelled = true
                    try {
                        const response = await fetch(
                            `${this.API_BASE}/tasks/${encodeURIComponent(this.taskId)}/cancel`,
                            { method: 'POST', headers: this.authHeaders }
                        )
                        if (!response.ok) {
                            this.analysisCancelled = false
                            throw new Error(await this.responseError(response, '取消任务'))
                        }
                        const payload = await response.json()
                        this.statusText = payload.status === 'cancel_requested'
                            ? `<span class="status-error">✗ 已请求取消任务 ${this.taskId}</span>`
                            : `<span class="status-error">✗ 任务 ${this.taskId} 已取消</span>`
                        this.loading = false
                        this.analysisPolling = false
                        this.analysisProgress = null
                    } catch (error) {
                        this.statusText =
                            `<span class="status-error">✗ ${this.escapeHtml(error.message)}</span>`
                    }
                },
                triggerVolumePicker(modality) {
                    document.getElementById(`volume-file-${modality}`)?.click()
                },
                toggleVolumeSourceMenu() {
                    this.volumeSourceMenuVisible = !this.volumeSourceMenuVisible
                    if (!this.volumeSourceMenuVisible) {
                        this.volumeCaseSourceMenuVisible = false
                    }
                },
                handleGlobalClick(event) {
                    const zone = this.$refs.volumeDropZone
                    if (zone && !zone.contains(event.target)) {
                        this.volumeSourceMenuVisible = false
                        this.volumeCaseSourceMenuVisible = false
                    }
                },
                toggleVolumeCaseSourceMenu() {
                    this.volumeCaseSourceMenuVisible = !this.volumeCaseSourceMenuVisible
                },
                triggerVolumeCaseFolderPicker() {
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    document.getElementById('volume-folder-picker')?.click()
                },
                triggerVolumeArchivePicker() {
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    document.getElementById('volume-archive-picker')?.click()
                },
                triggerVolumeManualPicker() {
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    this.volumeArchiveFile = null
                    this.volumeDicomFiles = []
                    this.volumeFolderLabel = ''
                    this.clearVolumeSelectionState()
                    this.volumeManualMode = true
                },
                volumeModalityFromFilename(filename) {
                    const normalized = filename
                        .replace(/\.nii(?:\.gz)?$/i, '')
                        .toLowerCase()
                    const tokens = new Set(normalized.split(/[_.-]+/).filter(Boolean))
                    const matches = this.volumeModalities
                        .map(modality => modality.key)
                        .filter(modality => tokens.has(modality))
                    return matches.length === 1 ? matches[0] : null
                },
                clearVolumeSelectionState() {
                    this.volumeSelectionIssues = {}
                    this.volumeSelectionCandidates = {}
                    this.volumeCandidateSelections = {}
                    this.archiveSelections = {}
                    this.volumeCorrectionVisible = true
                },
                confirmVolumeModality(modality) {
                    const { [modality]: resolvedIssue, ...remainingIssues } = this.volumeSelectionIssues
                    this.volumeSelectionIssues = remainingIssues
                    const { [modality]: resolvedCandidates, ...remainingCandidates } = this.volumeSelectionCandidates
                    this.volumeSelectionCandidates = remainingCandidates
                    const { [modality]: resolvedSelection, ...remainingSelections } = this.volumeCandidateSelections
                    this.volumeCandidateSelections = remainingSelections
                },
                selectVolumeFiles(files, sourceLabel) {
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    const selectedFiles = Array.from(files)
                    const candidates = { flair: [], t1ce: [], t1: [], t2: [] }
                    for (const file of selectedFiles) {
                        if (!/\.nii(?:\.gz)?$/i.test(file.name)) continue
                        const modality = this.volumeModalityFromFilename(file.name)
                        if (!modality) continue
                        candidates[modality].push(file)
                    }
                    if (!Object.values(candidates).some(items => items.length)) {
                        return this.selectDicomFiles(selectedFiles, sourceLabel)
                    }
                    const selected = {}
                    const issues = {}
                    for (const modality of this.volumeModalities) {
                        const options = candidates[modality.key]
                        selected[modality.key] = options.length === 1 ? options[0] : null
                        if (!options.length) {
                            issues[modality.key] = {
                                reason: 'missing',
                                message: `${sourceLabel}中未识别到 ${modality.label} 文件`,
                            }
                        } else if (options.length > 1) {
                            issues[modality.key] = {
                                reason: 'duplicate',
                                message: `${sourceLabel}中识别到 ${options.length} 个 ${modality.label} 候选文件`,
                            }
                        }
                    }
                    this.volumeFiles = selected
                    this.volumeArchiveFile = null
                    this.volumeDicomFiles = []
                    this.volumeFolderLabel = this.getVolumeFolderLabel(selectedFiles, sourceLabel)
                    this.volumeManualMode = false
                    this.volumeSelectionIssues = issues
                    this.volumeSelectionCandidates = candidates
                    this.volumeCandidateSelections = {}
                    this.archiveSelections = {}
                    this.dicomSeriesCandidates = {}
                    this.dicomSeriesSelections = {}
                    this.volumeCorrectionVisible = true
                    return !Object.keys(issues).length
                },
                selectDicomFiles(files, sourceLabel) {
                    if (!files.length) return false
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    this.volumeFiles = { flair: null, t1ce: null, t1: null, t2: null }
                    this.volumeArchiveFile = null
                    this.volumeDicomFiles = files
                    this.volumeFolderLabel = this.getVolumeFolderLabel(files, sourceLabel)
                    this.volumeManualMode = false
                    this.volumeSelectionIssues = {}
                    this.volumeSelectionCandidates = {}
                    this.volumeCandidateSelections = {}
                    this.archiveSelections = {}
                    this.dicomSeriesCandidates = {}
                    this.dicomSeriesSelections = {}
                    this.volumeCorrectionVisible = false
                    return true
                },
                onVolumeFolderSelected(event) {
                    this.selectVolumeFiles(event.target.files, '所选文件夹')
                    event.target.value = ''
                },
                onVolumeArchiveSelected(event) {
                    const file = event.target.files[0]
                    event.target.value = ''
                    if (!file) return
                    if (!/\.zip$/i.test(file.name)) {
                        this.statusText = '<span class="status-error">请选择 ZIP 压缩包。</span>'
                        return
                    }
                    this.setVolumeArchive(file)
                },
                async readDroppedEntry(entry) {
                    if (entry.isFile) {
                        return new Promise((resolve, reject) => entry.file(resolve, reject))
                    }
                    if (!entry.isDirectory) return []
                    const reader = entry.createReader()
                    const entries = []
                    while (true) {
                        const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject))
                        if (!batch.length) break
                        entries.push(...batch)
                    }
                    const nested = await Promise.all(entries.map(item => this.readDroppedEntry(item)))
                    return nested.flat()
                },
                async onVolumeDrop(event) {
                    this.volumeDropActive = false
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    try {
                        const droppedFiles = Array.from(event.dataTransfer?.files || [])
                        if (droppedFiles.length === 1 && /\.zip$/i.test(droppedFiles[0].name)) {
                            this.setVolumeArchive(droppedFiles[0])
                            return
                        }
                        const entries = Array.from(event.dataTransfer?.items || [])
                            .map(item => item.webkitGetAsEntry?.())
                            .filter(Boolean)
                        const collected = entries.length
                            ? (await Promise.all(entries.map(entry => this.readDroppedEntry(entry)))).flat()
                            : droppedFiles
                        if (collected.length === 1 && /\.zip$/i.test(collected[0].name)) {
                            this.setVolumeArchive(collected[0])
                            return
                        }
                        this.selectVolumeFiles(collected, '拖入内容')
                    } catch {
                        this.statusText = '<span class="status-error">无法读取拖入内容，请重新选择文件夹或 ZIP 压缩包。</span>'
                        this.analysisProgress = null
                    }
                },
                setVolumeArchive(file) {
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    this.volumeArchiveFile = file
                    this.volumeFiles = { flair: null, t1ce: null, t1: null, t2: null }
                    this.volumeDicomFiles = []
                    this.volumeFolderLabel = ''
                    this.volumeManualMode = false
                    this.dicomSeriesCandidates = {}
                    this.dicomSeriesSelections = {}
                    this.clearVolumeSelectionState()
                },
                getVolumeFolderLabel(files, fallbackLabel) {
                    const firstPath = Array.from(files)
                        .map(file => file.webkitRelativePath || '')
                        .find(Boolean)
                    return firstPath ? firstPath.split('/')[0] : fallbackLabel
                },
                clearVolumeUpload() {
                    this.volumeFiles = { flair: null, t1ce: null, t1: null, t2: null }
                    this.volumeArchiveFile = null
                    this.volumeDicomFiles = []
                    this.volumeFolderLabel = ''
                    this.volumeManualMode = false
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    this.dicomSeriesCandidates = {}
                    this.dicomSeriesSelections = {}
                    this.clearVolumeSelectionState()
                },
                applyVolumeCandidate(modality) {
                    const selectedIndex = Number(this.volumeCandidateSelections[modality])
                    const candidate = this.volumeSelectionCandidates[modality]?.[selectedIndex]
                    if (!candidate) return
                    if (this.volumeArchiveFile) {
                        this.archiveSelections[modality] = candidate.filename
                        this.volumeFiles[modality] = null
                        this.confirmVolumeModality(modality)
                        return
                    }
                    this.volumeFiles[modality] = candidate
                    this.confirmVolumeModality(modality)
                },
                onVolumeFileSelected(event, modality) {
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    const file = event.target.files[0]
                    if (!file) return
                    if (!file.name.match(/\.nii(?:\.gz)?$/i)) {
                        this.showToastMessage('请选择 .nii 或 .nii.gz 文件', 'error')
                        event.target.value = ''
                        this.volumeFiles[modality] = null
                        return
                    }
                    this.volumeFiles[modality] = file
                    this.confirmVolumeModality(modality)
                    if (!this.volumeArchiveFile) {
                        this.archiveSelections[modality] = ''
                    }
                },
                async gzipVolumeFileForUpload(file, label, fileIndex = 0, fileCount = 1) {
                    if (!/\.nii$/i.test(file.name)) return file
                    if (typeof CompressionStream === 'undefined') return file
                    try {
                        this.statusText =
                            `<span class="loading-spinner"></span>`
                            + `正在压缩 ${label}（${this.escapeHtml(file.name)}）...`
                        const compressor = new CompressionStream('gzip')
                        const writer = compressor.writable.getWriter()
                        const reader = compressor.readable.getReader()
                        const chunks = []
                        const readPromise = (async () => {
                            while (true) {
                                const { done, value } = await reader.read()
                                if (done) break
                                if (value && value.byteLength > 0) {
                                    chunks.push(value)
                                }
                            }
                        })()
                        const sliceBytes = 4 * 1024 * 1024
                        const total = file.size
                        let loaded = 0
                        for (let offset = 0; offset < total; offset += sliceBytes) {
                            const buffer = await file
                                .slice(offset, Math.min(total, offset + sliceBytes))
                                .arrayBuffer()
                            await writer.write(buffer)
                            loaded += buffer.byteLength
                            const fileFraction = loaded / total
                            const percent = Math.round(fileFraction * 100)
                            this.statusText =
                                `<span class="loading-spinner"></span>`
                                + `正在压缩 ${label}`
                                + `（${this.escapeHtml(file.name)}）... ${percent}%`
                            this.analysisProgress = {
                                percent: Math.min(
                                    12,
                                    Math.round(
                                        ((fileIndex + fileFraction) / fileCount) * 12
                                    )
                                ),
                                stage: '正在压缩/上传数据...',
                            }
                        }
                        await writer.close()
                        await readPromise
                        return new File(chunks, `${file.name}.gz`, {
                            type: 'application/gzip',
                        })
                    } catch {
                        return file
                    }
                },
                uploadTaskFiles(formData, endpoint = '/tasks/3d') {
                    return new Promise((resolve, reject) => {
                        const xhr = new XMLHttpRequest()
                        xhr.open('POST', `${this.API_BASE}${endpoint}`)
                        const token = localStorage.getItem('btir_token')
                        if (token) {
                            xhr.setRequestHeader('Authorization', `Bearer ${token}`)
                        }
                        xhr.upload.onprogress = (event) => {
                            if (event.lengthComputable && event.total > 0) {
                                const base = this.analysisProgress?.percent || 0
                                this.analysisProgress = {
                                    percent: Math.min(
                                        36,
                                        base + Math.round(
                                            (event.loaded / event.total) * (36 - base)
                                        )
                                    ),
                                    stage: '正在上传数据...',
                                }
                            }
                        }
                        xhr.onload = () => {
                            let payload = null
                            try {
                                payload = JSON.parse(xhr.responseText)
                            } catch {
                                payload = null
                            }
                            if (xhr.status >= 200 && xhr.status < 300) {
                                resolve(payload || {})
                                return
                            }
                            const detail = payload?.detail
                            const message = typeof detail === 'string'
                                ? detail
                                : (detail?.message || `创建任务失败: HTTP ${xhr.status}`)
                            const error = new Error(message)
                            error.payload = payload
                            reject(error)
                        }
                        xhr.onerror = () => reject(new Error('网络错误，创建任务失败'))
                        xhr.send(formData)
                    })
                },
                async recognizeFromUpload() {
                    if (!this.canRecognize) return
                    this.resetState()
                    this.clearWorkspaceState()
                    this.volumeCorrectionVisible = false

                    try {
                        const formData = new FormData()
                        let endpoint = '/tasks/3d'
                        if (this.volumeDicomFiles.length) {
                            for (const file of this.volumeDicomFiles) {
                                formData.append(
                                    'files',
                                    file,
                                    file.webkitRelativePath || file.name
                                )
                            }
                            for (const [modality, seriesUid] of Object.entries(this.dicomSeriesSelections)) {
                                if (seriesUid) {
                                    formData.append(`${modality}_series_uid`, seriesUid)
                                }
                            }
                            endpoint = '/tasks/3d/dicom'
                        } else if (this.volumeArchiveFile) {
                            formData.append('archive', this.volumeArchiveFile)
                            for (const modality of this.volumeModalities) {
                                const manualFile = this.volumeFiles[modality.key]
                                if (manualFile) {
                                    formData.append(modality.key, manualFile)
                                }
                                if (this.archiveSelections[modality.key]) {
                                    formData.append(
                                        `${modality.key}_entry`,
                                        this.archiveSelections[modality.key]
                                    )
                                }
                                if (this.dicomSeriesSelections[modality.key]) {
                                    formData.append(
                                        `${modality.key}_series_uid`,
                                        this.dicomSeriesSelections[modality.key]
                                    )
                                }
                            }
                            endpoint = '/tasks/3d/archive'
                        } else {
                            for (
                                let index = 0;
                                index < this.volumeModalities.length;
                                index++
                            ) {
                                const modality = this.volumeModalities[index]
                                const uploadFile = await this.gzipVolumeFileForUpload(
                                    this.volumeFiles[modality.key],
                                    modality.label,
                                    index,
                                    this.volumeModalities.length
                                )
                                formData.append(modality.key, uploadFile)
                            }
                        }
                        const uploadLabel = this.volumeArchiveFile?.name
                            || this.volumeFolderLabel
                            || '病例数据'
                        formData.append(
                            'name',
                            this.caseId ? `${this.caseName} · ${this.studyDate}` : uploadLabel,
                        )
                        if (this.caseId) {
                            formData.append('case_id', this.caseId)
                            formData.append('case_name', this.caseName)
                        }
                        formData.append('study_date', this.studyDate)
                        this.statusText =
                            '<span class="loading-spinner"></span>正在上传 '
                            + `${this.escapeHtml(uploadLabel)}...`

                        const createData = await this.uploadTaskFiles(formData, endpoint)
                        this.taskId = createData.task_id
                        this.persistWorkspaceState()
                        await this.runAndGetResult(this.taskId)
                    } catch (error) {
                        const selectionDetail = error.payload?.detail
                        if (selectionDetail?.code === 'archive_modality_selection_required') {
                            this.volumeSelectionIssues = selectionDetail.modalities || {}
                            this.volumeSelectionCandidates = Object.fromEntries(
                                this.volumeModalities.map(modality => [
                                    modality.key,
                                    selectionDetail.modalities?.[modality.key]?.candidates || [],
                                ])
                            )
                            this.volumeCandidateSelections = {}
                            this.archiveSelections = {}
                            this.volumeCorrectionVisible = true
                            this.statusText = '<span class="status-error">需要确认或补充模态文件后再提交。</span>'
                            this.analysisProgress = null
                            return
                        }
                        if (selectionDetail?.code === 'dicom_series_selection_required') {
                            this.loading = false
                            this.dicomSeriesCandidates = selectionDetail.modalities || {}
                            this.dicomSeriesSelections = {}
                            this.volumeCorrectionVisible = false
                            this.statusText = '<span class="status-error">请确认 DICOM 序列后再开始分析。</span>'
                            this.analysisProgress = null
                            return
                        }
                        this.statusText = `<span class="status-error">✗ ${this.escapeHtml(error.message)}</span>`
                        this.analysisProgress = null
                        console.error('识别错误:', error)
                    } finally {
                        this.loading = false
                    }
                },
                showToastMessage(message = '已复制到剪贴板', type = 'success') {
                    window.dispatchEvent(new CustomEvent('btir:toast', {
                        detail: { message, type },
                    }))
                },
                applyTheme() {
                    document.documentElement.setAttribute('data-theme', this.theme)
                },
                revealElement(el) {
                    el.classList.add('revealed')
                    const ring = el.dataset.ring
                    if (ring === 'classification') {
                        this.ringRevealed = true
                    } else if (ring === 'segmentation') {
                        this.segRingRevealed = true
                    } else if (ring === 'probability') {
                        this.probLineRevealed = true
                    }
                },
                revealIfInViewport(el) {
                    const rect = el.getBoundingClientRect()
                    const withinViewport = (
                        rect.top < window.innerHeight
                        && rect.bottom > 0
                        && rect.left < window.innerWidth
                        && rect.right > 0
                    )
                    if (withinViewport) {
                        this.revealElement(el)
                    }
                },
                registerScrollRevealTargets() {
                    const selectors = [
                        '.input-group',
                        '.volume-source-summary',
                        '.case-evidence-section',
                        '.analysis-summary',
                        '.region-overview',
                        '.case-meta-section',
                        '.task-query-row',
                        '.task-message',
                        '.task-empty',
                        '.task-case-group',
                    ]
                    document.querySelectorAll(selectors.join(',')).forEach((el) => {
                        if (!el.hasAttribute('data-reveal')) {
                            el.dataset.reveal = 'scroll'
                        }
                    })
                },
                initRevealObserver() {
                    this.registerScrollRevealTargets()
                    const targets = Array.from(document.querySelectorAll('[data-reveal]'))
                    if (!targets.length) return
                    this._revealObserver?.disconnect()
                    if (!('IntersectionObserver' in window)) {
                        targets.forEach(el => this.revealIfInViewport(el))
                        return
                    }
                    const observer = new IntersectionObserver((entries) => {
                        for (const entry of entries) {
                            if (!entry.isIntersecting) continue
                            this.revealElement(entry.target)
                            observer.unobserve(entry.target)
                        }
                    }, { threshold: 0.08 })
                    targets.forEach((el) => {
                        if (!el.classList.contains('revealed')) {
                            observer.observe(el)
                        }
                        this.revealIfInViewport(el)
                    })
                    this._revealObserver = observer
                },
                initScrollRevealFallback() {
                    if (this._scrollFallbackBound) return
                    this._scrollFallbackBound = true
                    const handler = () => {
                        document.querySelectorAll('[data-reveal]:not(.revealed)').forEach((el) => {
                            this.revealIfInViewport(el)
                        })
                    }
                    const containers = [
                        '.left-panel',
                        '.left-panel-scroll',
                        '.result-box',
                        '.right-content',
                        '.case-data-column',
                        '.task-manager',
                    ]
                    containers.forEach((selector) => {
                        document.querySelector(selector)?.addEventListener(
                            'scroll',
                            handler,
                            { passive: true },
                        )
                    })
                    window.addEventListener('scroll', handler, { passive: true })
                },
                toggleTheme() {
                    this.theme = this.theme === 'dark' ? 'light' : 'dark'
                    localStorage.setItem('btir_theme', this.theme)
                    this.applyTheme()
                },
                logout() {
                    localStorage.removeItem('btir_token')
                    localStorage.removeItem('btir_user')
                    this.clearWorkspaceState()
                    window.location.href = '/login/login.html'
                },
            },
            async mounted() {
                const savedTheme = localStorage.getItem('btir_theme')
                this.theme = savedTheme || 'light'
                this.applyTheme()
                this.$nextTick(() => this.initRevealObserver())
                this.initScrollRevealFallback()
                document.addEventListener('click', this.handleGlobalClick)
                window.addEventListener('resize', this.updateResultSplitViewport)
                window.addEventListener('keydown', this.handleCasePreviewKeydown)
                this.$nextTick(() => this.updateResultSplitViewport())

                const token = localStorage.getItem('btir_token')
                if (!token) {
                    window.location.href = '/login/login.html'
                    return
                }
                try {
                    const response = await fetch(`${this.API_BASE}/auth/me`, {
                        headers: this.authHeaders,
                    })
                    if (response.status === 401 || response.status === 403) {
                        this.logout()
                        return
                    }
                    if (response.ok) {
                        this.currentUser = await response.json()
                        localStorage.setItem('btir_user', JSON.stringify(this.currentUser))
                        if (this.currentUser.must_change_password) {
                            window.location.href = '/web/change-password.html'
                            return
                        }
                    }
                } catch {
                    const userStr = localStorage.getItem('btir_user')
                    this.currentUser = userStr ? JSON.parse(userStr) : null
                }
                await this.restoreWorkspaceState()
            },
            beforeUnmount() {
                this._revealObserver?.disconnect()
                if (this.progressAnimFrame) {
                    cancelAnimationFrame(this.progressAnimFrame)
                    this.progressAnimFrame = null
                }
                document.removeEventListener('click', this.handleGlobalClick)
                this.stopResultSplitResize()
                window.removeEventListener('resize', this.updateResultSplitViewport)
                window.removeEventListener('keydown', this.handleCasePreviewKeydown)
                if (this.resultSplitDrawFrame !== null) {
                    cancelAnimationFrame(this.resultSplitDrawFrame)
                    this.resultSplitDrawFrame = null
                }
                this.destroyVolumeViewer()
                this.clearCasePreview()
            },
        }
        const btirApp = createApp(btirRootOptions)
        if (window.BtirComponents) {
            Object.keys(window.BtirComponents).forEach((name) => {
                btirApp.component(name, window.BtirComponents[name])
            })
        }
        btirApp.mount('#app')
