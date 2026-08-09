;(function (global) {
    'use strict'
    const Vue = global.Vue
    if (!Vue) return

    const KEY_LABELS = {
        schema_version: '协议版本',
        task_id: '任务ID',
        created_at: '创建时间',
        updated_at: '更新时间',
        analysis_mode: '分析模式',
        status: '状态',
        completed_models: '已完成模型',
        result_files: '结果文件',
        frontend: '前端结果',
        classification: '分类结果',
        segmentation: '分割结果',
        mask: '分割掩码',
        input_files: '输入文件',
        flair: 'FLAIR',
        t1ce: 'T1CE',
        t1: 'T1',
        t2: 'T2',
        latest_runs: '最新运行',
        run_id: '运行ID',
        run_directory: '运行目录',
        model: '模型',
        model_metadata: '模型元数据',
        name: '名称',
        variant: '变体',
        weights: '权重',
        inference_mode: '推理模式',
        device: '设备',
        checkpoint: '检查点',
        spatial: '空间信息',
        shape: '尺寸',
        voxel_spacing_mm: '体素间距(mm)',
        orientation: '方向',
        affine: '仿射矩阵',
        labels: '标签',
        scheme: '标签方案',
        values: '取值',
        regions: '区域',
        volume_mm3: '体积(mm³)',
        voxels: '体素数',
        ratio: '占比',
        composites: '复合区域',
        morphology: '形态学',
        connected_components: '连通域数',
        largest_component_voxels: '最大连通域体素数',
        largest_component_volume_mm3: '最大连通域体积(mm³)',
        largest_component_ratio: '最大连通域占比',
        bounding_box_size_voxels: '包围盒尺寸(体素)',
        bounding_box_size_mm: '包围盒尺寸(mm)',
        bounding_box_fill_ratio: '包围盒填充率',
        centroid_normalized: '归一化质心',
        timing: '耗时',
        classification_inference_ms: '分类推理耗时(ms)',
        classification_breakdown: '分类耗时明细',
        prepare_ms: '预处理(ms)',
        model_setup_ms: '模型加载(ms)',
        model_inference_ms: '模型推理(ms)',
        postprocess_ms: '后处理(ms)',
        segmentation_inference_ms: '分割推理耗时(ms)',
        segmentation_breakdown: '分割耗时明细',
        load_validate_ms: '读取校验(ms)',
        normalize_ms: '归一化(ms)',
        save_ms: '保存(ms)',
        total_ms: '总计(ms)',
        supplementary_analysis: '综合分析',
        provider: '提供方',
        prompt_version: '提示词版本',
        generated_at: '生成时间',
        duration_ms: '耗时(ms)',
        usage: '用量',
        prompt_tokens: '提示词Token数',
        completion_tokens: '生成Token数',
        total_tokens: '总Token数',
        content: '内容',
        summary: '结论摘要',
        observations: '观察项',
        consistency: '一致性',
        uncertainties: '不确定项',
        follow_up: '建议',
        model_consensus: '模型共识',
        version: '版本',
        primary_evidence: '主要证据',
        segmentation_detected: '检出分割区域',
        segmentation_volume_mm3: '分割体积(mm³)',
        segmentation_voxel_count: '分割体素数',
        requires_review: '需要复核',
        probabilities: '概率',
        no: '阴性',
        yes: '阳性',
        threshold: '阈值',
        method: '方法',
        experimental: '实验性',
        modality: '模态',
        axis: '切面',
        evaluated_slices: '评估切片数',
        positive_slices: '阳性切片数',
        probability_statistics: '概率统计',
        mean_yes_probability: '阳性概率均值',
        stddev_yes_probability: '阳性概率标准差',
        min_yes_probability: '最小阳性概率',
        max_yes_probability: '最大阳性概率',
        median_yes_probability: '中位阳性概率',
        positive_slice_ratio: '阳性切片占比',
        threshold_margin: '阈值差值',
        positive_slice_structure: '阳性切片结构',
        positive_runs: '阳性连续段数',
        longest_positive_run_samples: '最长连续段',
        positive_span_samples: '阳性跨度',
        probability_histogram: '概率直方图',
        lower: '下界',
        upper: '上界',
        count: '数量',
        slice_probability_series: '切片概率序列',
        slice_index: '切片序号',
        yes_probability: '阳性概率',
        aggregation: '聚合方式',
        evidence_slices: '证据切片',
        input_summary: '输入摘要',
        canonical_shape: '标准尺寸',
        foreground_slices: '前景切片数',
        intensity_window: '强度窗',
        class: '结论',
        class_id: '结论ID',
        confidence: '置信度',
        label: '标签',
        error: '错误',
    }

    const registry = global.BtirComponents || (global.BtirComponents = {})
    registry['btir-detail-table'] = {
        props: {
            sources: { type: Array, default: () => [] },
            fileUrl: { type: Function, required: true },
            headers: { type: Object, default: () => ({}) },
        },
        emits: ['copied'],
        data() {
            return {
                sections: [],
                loading: false,
                _loaded: false,
            }
        },
        computed: {
            rowCount() {
                return this.sections.reduce(
                    (sum, section) => sum + section.rows.length,
                    0,
                )
            },
        },
        watch: {
            sources() {
                this.sections = []
                this._loaded = false
                if (this.sources.length) {
                    this.open()
                }
            },
        },
        mounted() {
            if (this.sources.length) {
                this.open()
            }
        },
        methods: {
            async open() {
                if (!this.sources.length || this._loaded) return
                this._loaded = true
                this.loading = true
                this.sections = []
                try {
                    const loaded = await Promise.all(this.sources.map(async (source) => {
                        const response = await fetch(this.fileUrl(source.path), {
                            headers: this.headers,
                        })
                        if (!response.ok) {
                            throw new Error(`HTTP ${response.status}`)
                        }
                        const text = await response.text()
                        let data = {}
                        try {
                            data = JSON.parse(text)
                        } catch {
                            data = {}
                        }
                        return { label: source.label, data }
                    }))
                    this.sections = loaded.map(({ label, data }) => ({
                        label,
                        rows: this.buildCuratedRows(data),
                    }))
                } catch (err) {
                    this._loaded = false
                    this.sections = [{
                        label: '读取失败',
                        rows: [{
                            key: 'error',
                            value: `读取结果文件失败：${err.message}`,
                            full: '',
                            level: 0,
                            hasChildren: false,
                            collapsed: false,
                        }],
                    }]
                } finally {
                    this.loading = false
                }
            },
            flattenKeyValuePairs(data) {
                const rows = []
                const append = (key, value, level, hasChildren, full) => {
                    const displayKey = this.translateKey(key)
                    rows.push({
                        key: displayKey,
                        rawKey: displayKey === key ? '' : key,
                        value,
                        level,
                        hasChildren: Boolean(hasChildren),
                        full: full || '',
                        collapsed: Boolean(hasChildren),
                    })
                }
                const walk = (node, displayKey, level) => {
                    if (node === null) {
                        append(displayKey, 'null', level)
                        return
                    }
                    if (Array.isArray(node)) {
                        if (node.length === 0) {
                            append(displayKey, '[]', level)
                            return
                        }
                        if (node.every(item => item === null || typeof item !== 'object')) {
                            append(
                                displayKey,
                                `[${node.map(item => this.formatListValue(item)).join(', ')}]`,
                                level,
                            )
                            return
                        }
                        append(displayKey, '', level, true, `共 ${node.length} 项`)
                        const visibleCount = Math.min(node.length, 12)
                        for (let index = 0; index < visibleCount; index++) {
                            const item = node[index]
                            if (item !== null && typeof item === 'object') {
                                walk(item, `[${index}]`, level + 1)
                            } else {
                                append(`[${index}]`, this.formatListValue(item), level + 1)
                            }
                        }
                        if (node.length > visibleCount) {
                            append(
                                '…',
                                `共 ${node.length} 项，仅显示前 ${visibleCount} 项`,
                                level + 1,
                            )
                        }
                        return
                    }
                    if (typeof node === 'object') {
                        const entries = Object.entries(node)
                        if (entries.length === 0) {
                            append(displayKey, '{}', level)
                            return
                        }
                        append(displayKey, '', level, true, `${entries.length} 项`)
                        for (const [childKey, childValue] of entries) {
                            walk(childValue, childKey, level + 1)
                        }
                        return
                    }
                    const formatted = this.formatListValue(node)
                    const full = (
                        typeof node === 'string' && node.length > 240
                    ) ? node : ''
                    append(displayKey, formatted, level, false, full)
                }
                for (const [key, value] of Object.entries(data)) {
                    walk(value, key, 0)
                }
                return rows
            },
            translateKey(key) {
                if (typeof key !== 'string' || !key) return key
                if (key.startsWith('[') || key === '…') return key
                return KEY_LABELS[key] || key
            },
            buildCuratedRows(data) {
                const rows = []
                const formatLeaf = (value) => {
                    if (Array.isArray(value)) {
                        return `[${value.map(item => this.formatListValue(item)).join(', ')}]`
                    }
                    return this.formatListValue(value)
                }
                const addLeaf = (key, value, level) => {
                    if (value === undefined || value === null || value === '') return
                    const full = (
                        typeof value === 'string' && value.length > 240
                    ) ? value : ''
                    rows.push({
                        key: this.translateKey(key),
                        rawKey: '',
                        value: formatLeaf(value),
                        level,
                        hasChildren: false,
                        full,
                        collapsed: false,
                    })
                }
                const addGroup = (key, level, collapsed, buildChildren) => {
                    const start = rows.length
                    buildChildren()
                    const count = rows.length - start
                    rows.splice(start, 0, {
                        key: this.translateKey(key),
                        rawKey: '',
                        value: '',
                        level,
                        hasChildren: true,
                        full: `${count} 项`,
                        collapsed,
                    })
                }

                const classification = data.classification || {}
                const segmentation = data.segmentation || {}
                const consensus = data.model_consensus || null
                const supplementary = data.supplementary_analysis || null

                addGroup('分类判断', 0, false, () => {
                    addLeaf('class', classification.class, 1)
                    addLeaf('confidence', classification.confidence, 1)
                    addLeaf('threshold', classification.threshold, 1)
                    if (classification.probabilities) {
                        addGroup('概率', 1, true, () => {
                            addLeaf('no', classification.probabilities.no, 2)
                            addLeaf('yes', classification.probabilities.yes, 2)
                        })
                    }
                })

                addGroup('分割判断', 0, true, () => {
                    if (segmentation.regions) {
                        addGroup('区域', 1, true, () => {
                            for (const [label, region] of Object.entries(segmentation.regions)) {
                                if (label === '0') continue
                                addGroup(label === '0' ? '背景' : label, 2, true, () => {
                                    addLeaf('name', region && region.name, 3)
                                    addLeaf('volume_mm3', region && region.volume_mm3, 3)
                                    addLeaf('ratio', region && region.ratio, 3)
                                })
                            }
                        })
                    }
                    if (segmentation.composites) {
                        addGroup('复合区域', 1, true, () => {
                            for (const [label, composite] of Object.entries(segmentation.composites)) {
                                addGroup(label, 2, true, () => {
                                    addLeaf('volume_mm3', composite && composite.volume_mm3, 3)
                                    addLeaf('ratio', composite && composite.ratio, 3)
                                })
                            }
                        })
                    }
                })

                if (consensus) {
                    addGroup('模型共识', 0, true, () => {
                        addLeaf('consistency', consensus.consistency, 1)
                        addLeaf('segmentation_detected', consensus.segmentation_detected, 1)
                        addLeaf('segmentation_volume_mm3', consensus.segmentation_volume_mm3, 1)
                        addLeaf('requires_review', consensus.requires_review, 1)
                        addLeaf('summary', consensus.summary, 1)
                    })
                }

                if (supplementary && supplementary.status !== 'disabled') {
                    addGroup('综合分析', 0, false, () => {
                        if (supplementary.status === 'succeeded') {
                            const content = supplementary.content || {}
                            addLeaf('summary', content.summary, 1)
                            addLeaf('consistency', content.consistency, 1)
                            const observationList = Array.isArray(content.observations)
                                ? content.observations
                                : []
                            if (observationList.length) {
                                addGroup('观察项', 1, true, () => {
                                    observationList.forEach((item, index) => {
                                        addLeaf(`观察 ${index + 1}`, item, 2)
                                    })
                                })
                            }
                            addLeaf('uncertainties', content.uncertainties, 1)
                            addLeaf('follow_up', content.follow_up, 1)
                        } else {
                            addLeaf('message', supplementary.message, 1)
                        }
                    })
                }

                return rows
            },
            visibleRows(section) {
                const visible = []
                const collapsedAncestors = []
                for (const row of section.rows) {
                    while (
                        collapsedAncestors.length
                        && row.level <= collapsedAncestors[collapsedAncestors.length - 1]
                    ) {
                        collapsedAncestors.pop()
                    }
                    if (!collapsedAncestors.length) {
                        visible.push(row)
                    }
                    if (row.hasChildren && row.collapsed) {
                        collapsedAncestors.push(row.level)
                    }
                }
                return visible
            },
            toggleRow(row) {
                if (row.hasChildren) {
                    row.collapsed = !row.collapsed
                }
            },
            formatListValue(value) {
                if (value === null) return 'null'
                if (typeof value === 'boolean') {
                    return value ? 'true' : 'false'
                }
                if (typeof value === 'number') {
                    if (!Number.isFinite(value)) return String(value)
                    if (Number.isInteger(value)) return String(value)
                    return String(Math.round(value * 1e6) / 1e6)
                }
                if (typeof value === 'string') {
                    if (value.length > 240) {
                        return `${value.slice(0, 240)}…`
                    }
                    return value
                }
                return String(value)
            },
            copyDetail() {
                const text = this.sections.map((section) => {
                    const lines = section.rows.map((row) => {
                        const indent = '  '.repeat(row.level)
                        const line = row.hasChildren
                            ? `- ${row.key}${row.full ? `（${row.full}）` : ''}`
                            : `- ${row.key}: ${row.value}`
                        return `${indent}${line}`
                    })
                    return lines.join('\n')
                }).join('\n\n')
                const notify = () => this.$emit('copied')
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(text).then(notify).catch(() => {
                        this._fallbackCopy(text)
                        notify()
                    })
                } else {
                    this._fallbackCopy(text)
                    notify()
                }
            },
            _fallbackCopy(text) {
                const ta = document.createElement('textarea')
                ta.value = text
                document.body.appendChild(ta)
                ta.select()
                document.execCommand('copy')
                document.body.removeChild(ta)
            },
        },
        template: `
            <div class="md-table-viewer">
                <div class="md-table-loading" v-if="loading">
                    <span class="loading-spinner"></span>
                    正在整合结果文件...
                </div>
                <template v-else>
                    <div class="md-table-overview" v-if="sections.length">
                        <span>{{ rowCount }} 个键值项</span>
                        <button class="md-table-copy" @click="copyDetail">
                            <svg class="icon" viewBox="0 0 16 16" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                                <rect x="5.5" y="5.5" width="8" height="8" rx="1.5"></rect>
                                <path d="M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5"></path>
                            </svg>
                            复制
                        </button>
                    </div>
                    <div
                        class="md-table-section"
                        v-for="section in sections"
                        :key="section.label"
                    >
                        <table class="md-table">
                            <tbody>
                                <tr v-if="!section.rows.length">
                                    <td colspan="2" class="md-table-empty">（空）</td>
                                </tr>
                                <tr
                                    v-for="(row, index) in visibleRows(section)"
                                    :key="\`\${section.label}-\${index}\`"
                                    :class="['md-table-row', { 'md-table-group': row.hasChildren }]"
                                    @click="row.hasChildren && toggleRow(row)"
                                >
                                    <td
                                        class="md-table-key"
                                        :style="{ paddingLeft: (12 + row.level * 20) + 'px' }"
                                        :title="row.rawKey || undefined"
                                    >
                                        <template v-if="row.hasChildren">
                                            <span class="md-table-toggle">{{ row.collapsed ? '▸' : '▾' }}</span>
                                            {{ row.key }}
                                            <span class="md-table-count" v-if="row.full">（{{ row.full }}）</span>
                                        </template>
                                        <template v-else>{{ row.key }}</template>
                                    </td>
                                    <td
                                        class="md-table-value"
                                        :title="row.full || row.value"
                                    >
                                        <span v-if="row.hasChildren" class="md-table-hint">
                                            {{ row.collapsed ? '点击展开' : '点击折叠' }}
                                        </span>
                                        <template v-else>{{ row.value }}</template>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </template>
            </div>
        `,
    }
})(window)
