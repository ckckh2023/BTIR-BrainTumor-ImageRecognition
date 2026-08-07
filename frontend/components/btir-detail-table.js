;(function (global) {
    'use strict'
    const Vue = global.Vue
    if (!Vue) return

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
                        rows: this.flattenKeyValuePairs(data),
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
                    rows.push({
                        key,
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
