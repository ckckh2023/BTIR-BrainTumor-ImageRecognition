/*
 * BTIR NIfTI viewer adapter.
 *
 * Rendering and NIfTI parsing are provided by NiiVue 0.69.0 (BSD-2-Clause).
 * See THIRD_PARTY_NOTICES.md for attribution and license details.
 */
(function attachBtirVolumeViewer(global) {
    'use strict'

    const adapterUrl = document.currentScript?.src || document.baseURI
    const niivueUrl = new URL('./vendor/niivue.umd.js', adapterUrl).href
    let niivueLoadPromise = null

    const MASK_COLORMAP = {
        R: [0, 239, 34, 250],
        G: [0, 68, 197, 204],
        B: [0, 68, 94, 21],
        A: [0, 255, 255, 255],
        I: [0, 1, 2, 4],
        labels: ['背景', 'NCR/NET', 'ED', 'ET'],
    }

    function ensureNiiVue() {
        if (global.niivue?.Niivue) return Promise.resolve()
        if (niivueLoadPromise) return niivueLoadPromise

        niivueLoadPromise = new Promise((resolve, reject) => {
            const script = document.createElement('script')
            script.src = niivueUrl
            script.async = true
            script.dataset.btirNiivue = '0.69.0'
            script.onload = () => {
                if (global.niivue?.Niivue) {
                    resolve()
                } else {
                    reject(new Error('NiiVue 组件加载后未提供查看器接口'))
                }
            }
            script.onerror = () => reject(new Error('NiiVue 组件加载失败'))
            document.head.appendChild(script)
        }).catch(error => {
            niivueLoadPromise = null
            throw error
        })
        return niivueLoadPromise
    }

    class BtirVolumeViewer {
        constructor(canvas) {
            if (!(canvas instanceof HTMLCanvasElement)) {
                throw new TypeError('3D 查看器需要有效的 canvas 元素')
            }
            if (!global.WebGL2RenderingContext) {
                throw new Error('当前浏览器或设备不支持 WebGL2')
            }

            this.canvas = canvas
            this.viewer = null
            this.initializing = null
            this.abortController = null
            this.requestId = 0
            this.maskCache = null
            this.viewMode = 'multiplanar'
        }

        async initialize() {
            if (this.viewer) return
            if (this.initializing) {
                await this.initializing
                return
            }

            this.initializing = (async () => {
                await ensureNiiVue()
                const viewer = new global.niivue.Niivue({
                    backColor: [0.035, 0.055, 0.09, 1],
                    crosshairColor: [0.94, 0.97, 1, 0.8],
                    dragAndDropEnabled: false,
                    isColorbar: false,
                    isResizeCanvas: true,
                    show3Dcrosshair: true,
                })
                await viewer.attachToCanvas(this.canvas)
                viewer.setMultiplanarLayout(
                    global.niivue.MULTIPLANAR_TYPE?.GRID ?? 2
                )
                viewer.setMultiplanarPadPixels(3)
                this.viewer = viewer
                this.setViewMode(this.viewMode)
            })()

            try {
                await this.initializing
            } finally {
                this.initializing = null
            }
        }

        async load({
            base,
            mask = null,
            headers = {},
            maskOpacity = 0.55,
            maskVisible = true,
            viewMode = 'multiplanar',
            onProgress = null,
        }) {
            this.validateSource(base, '基础模态')
            if (mask) this.validateSource(mask, '分割掩码')

            await this.initialize()
            this.abortController?.abort()
            const controller = new AbortController()
            this.abortController = controller
            const requestId = ++this.requestId

            const progressEntries = new Map()
            const reportProgress = () => {
                if (typeof onProgress !== 'function') return
                let loaded = 0
                let total = 0
                let label = ''
                let hasKnownTotal = false
                for (const entry of progressEntries.values()) {
                    if (entry.total > 0) {
                        hasKnownTotal = true
                        total += entry.total
                        loaded += Math.min(entry.loaded, entry.total)
                    }
                    label = entry.label
                }
                onProgress({
                    label,
                    loaded,
                    total,
                    indeterminate: !hasKnownTotal,
                })
            }

            const basePromise = this.fetchArrayBuffer(
                base,
                headers,
                controller.signal,
                (loaded, total) => {
                    progressEntries.set('base', {
                        loaded,
                        total,
                        label: base.name,
                    })
                    reportProgress()
                }
            )
            const maskPromise = mask
                ? this.getMaskArrayBuffer(
                    mask,
                    headers,
                    controller.signal,
                    (loaded, total) => {
                        progressEntries.set('mask', {
                            loaded,
                            total,
                            label: mask.name,
                        })
                        reportProgress()
                    }
                )
                : Promise.resolve(null)
            const [baseBuffer, maskBuffer] = await Promise.all([
                basePromise,
                maskPromise,
            ])

            if (requestId !== this.requestId) return
            this.clearVolumes()
            await this.viewer.loadFromArrayBuffer(baseBuffer, base.name)
            if (requestId !== this.requestId) {
                this.clearVolumes()
                return
            }

            const baseVolume = this.viewer.volumes[0]
            if (baseVolume) {
                this.viewer.setColormap(baseVolume.id, 'gray')
            }

            if (mask && maskBuffer) {
                await this.viewer.loadFromArrayBuffer(
                    maskBuffer.slice(0),
                    mask.name
                )
                if (requestId !== this.requestId) {
                    this.clearVolumes()
                    return
                }
                const maskVolume = this.viewer.volumes[1]
                maskVolume?.setColormapLabel(MASK_COLORMAP)
                this.setMaskOpacity(maskVisible ? maskOpacity : 0)
            }

            this.viewer.updateGLVolume()
            this.setViewMode(viewMode)
        }

        validateSource(source, label) {
            if (!source?.url || !source?.name) {
                throw new Error(`${label}文件信息不完整`)
            }
            if (!/\.nii(?:\.gz)?$/i.test(source.name)) {
                throw new Error(`${label}必须是 .nii 或 .nii.gz 文件`)
            }
        }

        async fetchArrayBuffer(source, headers, signal, onProgress = null) {
            const response = await fetch(source.url, {
                headers: { ...headers },
                signal,
            })
            if (!response.ok) {
                throw new Error(`${source.name} 读取失败：HTTP ${response.status}`)
            }
            const total = Number(response.headers.get('content-length')) || 0
            if (!response.body || typeof response.body.getReader !== 'function') {
                onProgress?.(0, total, source.name)
                return response.arrayBuffer()
            }

            const reader = response.body.getReader()
            const chunks = []
            let loaded = 0
            while (true) {
                const { done, value } = await reader.read()
                if (done) break
                if (value && value.byteLength > 0) {
                    chunks.push(value)
                    loaded += value.byteLength
                    onProgress?.(loaded, total, source.name)
                }
            }
            if (loaded === 0) {
                return new ArrayBuffer(0)
            }
            const merged = new Uint8Array(loaded)
            let offset = 0
            for (const chunk of chunks) {
                merged.set(chunk, offset)
                offset += chunk.byteLength
            }
            return merged.buffer
        }

        async getMaskArrayBuffer(source, headers, signal, onProgress = null) {
            if (this.maskCache?.url === source.url) {
                return this.maskCache.buffer
            }
            const buffer = await this.fetchArrayBuffer(
                source,
                headers,
                signal,
                onProgress
            )
            this.maskCache = {
                url: source.url,
                buffer,
            }
            return buffer
        }

        setMaskOpacity(opacity) {
            if (!this.viewer || this.viewer.volumes.length < 2) return
            const normalized = Math.min(1, Math.max(0, Number(opacity) || 0))
            this.viewer.setOpacity(1, normalized)
        }

        setViewMode(mode) {
            if (!['multiplanar', 'render'].includes(mode)) return
            this.viewMode = mode
            if (!this.viewer) return

            const sliceType = mode === 'render'
                ? global.niivue.SLICE_TYPE?.RENDER
                : global.niivue.SLICE_TYPE?.MULTIPLANAR
            if (sliceType !== undefined) {
                this.viewer.setSliceType(sliceType)
            }
            if (mode === 'multiplanar' && global.niivue.SHOW_RENDER) {
                this.viewer.opts.multiplanarShowRender =
                    global.niivue.SHOW_RENDER.NEVER
            }
            this.viewer.drawScene()
        }

        clearVolumes() {
            if (!this.viewer) return
            while (this.viewer.volumes.length) {
                this.viewer.removeVolumeByIndex(this.viewer.volumes.length - 1)
            }
        }

        cleanup() {
            this.requestId += 1
            this.abortController?.abort()
            this.abortController = null
            this.maskCache = null
            if (this.viewer) {
                this.clearVolumes()
                this.viewer.cleanup()
                this.viewer = null
            }
        }
    }

    global.BtirVolumeViewer = BtirVolumeViewer
})(window)
