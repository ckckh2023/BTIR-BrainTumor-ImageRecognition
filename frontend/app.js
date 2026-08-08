        const { createApp } = Vue

        const btirRootOptions = {
            data() {
                return {
                    API_BASE: '',
                    loading: false,
                    analysisCancelled: false,
                    analysisPolling: false,
                    analysisProgress: null,
                    statusText: '等待识别...',
                    taskId: '',
                    analysisActive: false,
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
                    selectedFilePath: '',
                    selectedFileType: '',
                    selectedFileLabel: '',
                    fileLoading: false,
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
                    activeRightView: 'results',
                    taskItems: [],
                    taskTotal: 0,
                    taskLimit: 10,
                    taskOffset: 0,
                    taskQuery: '',
                    taskStatusFilter: '',
                    taskListMode: 'active',
                    taskHistoryLoading: false,
                    taskActionId: '',
                    taskRunHistoryTaskId: '',
                    taskRunHistoryItems: [],
                    taskRunHistoryLoading: false,
                    taskMessage: '',
                    taskMessageIsError: false,
                    currentUser: null,
                    theme: 'light',
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
                analysisProgressPercent() {
                    const progress = this.analysisProgress
                    if (!progress || typeof progress.percent !== 'number') return 0
                    return Math.min(100, Math.max(0, Math.round(progress.percent)))
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
            },
            watch: {
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
                switchRightView(view) {
                    this.activeRightView = view
                    if (view === 'tasks') {
                        if (!this.taskItems.length && !this.taskHistoryLoading) {
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
                regionBarWidth(region) {
                    const max = Math.max(...this.regionStats.map(item => item.volumeMm3), 0)
                    if (!max) return '0%'
                    const ratio = Math.max(0, Math.min(1, region.volumeMm3 / max))
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
                analysisConsistencyLabel(value) {
                    const labels = {
                        consistent: '分类与分割证据大致一致',
                        inconclusive: '证据不足，无法得出稳定综合说明',
                        conflicting: '分类与分割证据存在不一致',
                    }
                    return labels[value] || '未说明'
                },
                supplementaryRecommendation(analysis) {
                    const followUp = analysis?.content?.follow_up
                    if (typeof followUp === 'string' && followUp.trim()) {
                        return followUp.trim()
                    }
                    const hasSegmentedRegion = this.tumorArea !== null && this.tumorArea > 0
                    const classificationPositive = this.classificationLabel === '肿瘤 detected'
                    if (classificationPositive && hasSegmentedRegion) {
                        return '结合原始多模态 MRI 和分割掩码进行针对性影像复核；如有既往检查，可进行同部位对比。'
                    }
                    if (!classificationPositive && !hasSegmentedRegion) {
                        return '结合当前症状和既往检查进行常规随访；症状持续或加重时，可进一步进行专业影像评估。'
                    }
                    return '优先核查分割掩码、高概率切片和输入质量；必要时补充人工影像评估。'
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
                        this.taskItems = Array.isArray(payload.items) ? payload.items : []
                        this.taskTotal = Number(payload.total) || 0
                    } catch (error) {
                        this.taskItems = []
                        this.taskTotal = 0
                        this.taskMessage = error.message
                        this.taskMessageIsError = true
                    } finally {
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
                    this.selectedFileLabel = ''
                    this.integratedSources = []
                    this.volumeViewerSources = null
                    this.volumeViewerError = ''
                    this.volumeViewerLoading = false
                    this.classificationLabel = ''
                    this.confidence = 0
                    this.tumorArea = null
                    this.regionStats = []
                    this.probabilitySeries = []
                    this.probabilityThreshold = 0.548381
                    this.chartHover = null
                    this.chartHoverVisible = false
                    this.modelConsensus = null
                    this.supplementaryAnalysis = null
                },
                startNewUpload() {
                    this.resetState()
                    this.loading = false
                    this.analysisActive = false
                    this.analysisProgress = null
                    this.statusText = '等待识别...'
                    this.volumeFiles = { flair: null, t1ce: null, t1: null, t2: null }
                    this.volumeArchiveFile = null
                    this.volumeDicomFiles = []
                    this.volumeFolderLabel = ''
                    this.volumeManualMode = false
                    this.volumeDropActive = false
                    this.volumeSourceMenuVisible = false
                    this.volumeCaseSourceMenuVisible = false
                    this.dicomSeriesCandidates = {}
                    this.dicomSeriesSelections = {}
                    this.clearVolumeSelectionState()
                },
                openSampleGuide() {
                    window.location.href = 'guide.html'
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
                            label: '详细结果',
                            path: '@integrated',
                            type: 'integrated',
                            sources: { files: jsonFiles },
                        })
                    }

                    if (Object.keys(modalities).length) {
                        files.push({
                            label: '3D查看',
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
                async openVolumeViewer(file) {
                    if (!file.sources?.modalities) return
                    if (
                        this.selectedFileType === 'volume'
                        && this.selectedFilePath === file.path
                        && this.volumeViewer
                    ) {
                        return
                    }

                    this.destroyVolumeViewer()
                    this.selectedFilePath = file.path
                    this.selectedFileType = 'volume'
                    this.selectedFileLabel = file.label
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
                async loadSelectedVolume() {
                    const sources = this.volumeViewerSources
                    const base = sources?.modalities?.[this.selectedVolumeModality]
                    const canvas = this.$refs.volumeCanvas
                    if (!sources || !base || !canvas) return

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
                    this.volumeViewer?.cleanup()
                    this.volumeViewer = null
                    this.volumeViewerLoading = false
                    this.volumeDownload = null
                },
                selectFile(f) {
                    if (f.type === 'download') {
                        this.downloadTaskFile(f)
                        return
                    }
                    if (f.type === 'volume') {
                        this.openVolumeViewer(f)
                        return
                    }
                    if (f.type === 'integrated') {
                        this.destroyVolumeViewer()
                        this.selectedFilePath = f.path
                        this.selectedFileType = 'integrated'
                        this.selectedFileLabel = f.label
                        return
                    }
                },
                async downloadTaskFile(file) {
                    const previousPath = this.selectedFilePath
                    this.fileLoading = true
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
                        this.fileLoading = false
                        this.selectedFilePath = previousPath
                    }
                },
                presentTaskResult(taskData) {
                    this.destroyVolumeViewer()
                    this.taskId = taskData.task_id
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
                    this.modelConsensus = resultData.model_consensus || null
                    this.supplementaryAnalysis = resultData.supplementary_analysis || null
                    if (resultData.classification) {
                        const classification = resultData.classification
                        this.classificationLabel = classification.class === 'yes'
                            ? '肿瘤 detected'
                            : '正常'
                        this.confidence = classification.confidence
                        this.probabilitySeries = Array.isArray(
                            classification.slice_probability_series
                        ) ? classification.slice_probability_series : []
                        this.probabilityThreshold = classification.threshold || 0.548381
                    }
                    if (resultData.segmentation) {
                        const regions = resultData.segmentation.regions || {}
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

                    this.fileList = this.buildFileList(resultData, taskData)
                    this.selectedFilePath = ''
                    this.selectedFileType = ''
                    this.volumeViewerSources = null
                    this.volumeViewerError = ''
                    this.activeRightView = 'results'
                    const volumeEntry = this.fileList.find(file => file.type === 'volume')
                    if (volumeEntry) {
                        const base = volumeEntry.sources.modalities[this.selectedVolumeModality]
                            || Object.values(volumeEntry.sources.modalities)[0]
                        if (base) {
                            fetch(this.taskFileUrl(base.path), {
                                headers: this.authHeaders,
                            }).catch(() => {})
                        }
                        if (volumeEntry.sources.mask) {
                            fetch(this.taskFileUrl(volumeEntry.sources.mask.path), {
                                headers: this.authHeaders,
                            }).catch(() => {})
                        }
                    }
                    const detailEntry = this.fileList.find(file => file.type === 'integrated')
                    if (detailEntry) {
                        this.selectFile(detailEntry)
                    }
                    this.$nextTick(() => this.initRevealObserver())
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
                                this.presentTaskResult(resultData)
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
                        formData.append('name', 'web-3d-analysis')
                        const uploadLabel = this.volumeArchiveFile?.name
                            || this.volumeFolderLabel
                            || '病例数据'
                        this.statusText =
                            '<span class="loading-spinner"></span>正在上传 '
                            + `${this.escapeHtml(uploadLabel)}...`

                        const createData = await this.uploadTaskFiles(formData, endpoint)
                        this.taskId = createData.task_id
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
                initRevealObserver() {
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
                    window.location.href = '/login/login.html'
                },
            },
            async mounted() {
                window.BtirVolumeViewer?.preload?.()
                const savedTheme = localStorage.getItem('btir_theme')
                this.theme = savedTheme || 'light'
                this.applyTheme()
                this.$nextTick(() => this.initRevealObserver())
                this.initScrollRevealFallback()
                document.addEventListener('click', this.handleGlobalClick)

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
                    }
                } catch {
                    const userStr = localStorage.getItem('btir_user')
                    this.currentUser = userStr ? JSON.parse(userStr) : null
                }
            },
            beforeUnmount() {
                this._revealObserver?.disconnect()
                document.removeEventListener('click', this.handleGlobalClick)
                this.destroyVolumeViewer()
            },
        }
        const btirApp = createApp(btirRootOptions)
        if (window.BtirComponents) {
            Object.keys(window.BtirComponents).forEach((name) => {
                btirApp.component(name, window.BtirComponents[name])
            })
        }
        btirApp.mount('#app')
