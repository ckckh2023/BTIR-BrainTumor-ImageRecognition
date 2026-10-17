const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const frontend = path.join(__dirname, '../frontend')
const context = { window: {}, Vue: { createApp: () => ({ mount() {} }) } }
vm.createContext(context)
vm.runInContext(fs.readFileSync(path.join(frontend, 'analysis-progress.js'), 'utf8'), context)
vm.runInContext(fs.readFileSync(path.join(frontend, 'app.js'), 'utf8'), context)
const Progress = context.BtirAnalysisProgress
const app = vm.runInContext('btirRootOptions', context)

function tick(model, value, start, end, fps = 60) {
    model.lastFrameAt = start
    for (let time = start + 1000 / fps; time < end; time += 1000 / fps) {
        value = model.advance(value, time)
    }
    return model.advance(value, end)
}

function pipeline(fps, scale = 1) {
    const model = new Progress()
    let value = 0
    const snapshots = []
    for (let frame = 0; frame <= 160 * scale * fps; frame++) {
        const time = frame * 1000 / fps
        const seconds = time / 1000 / scale
        let phase, raw
        if (seconds < 15) { phase = 'upload'; raw = seconds / 15 * 36 }
        else if (seconds < 30) { phase = 'classification'; raw = 36 }
        else if (seconds < 140) { phase = 'segmentation'; raw = 44 + (seconds - 30) / 110 * 54 }
        else { phase = 'summary'; raw = 99 }
        model.update(phase, raw, time)
        const previous = value
        value = model.advance(value, time)
        assert(value >= previous, 'the same task never moves backwards')
        assert(value <= model.ceiling, `${phase} does not cross its ceiling`)
        if (phase === 'segmentation') assert(value <= model.mappedPercent + 2)
        assert(value < 100, 'running jobs cannot display completion')
        if (frame % (10 * scale * fps) === 0) snapshots.push(value)
    }
    return { model, value, snapshots }
}

test('160-second reference flow reserves most of the bar for segmentation and a final summary interval', () => {
    const { snapshots, model, value } = pipeline(60)
    assert(snapshots[1] > 6 && snapshots[1] < 7)
    assert(snapshots[2] > 14 && snapshots[2] < 17)
    assert(snapshots[8] > 50 && snapshots[8] < 55)
    assert(snapshots[14] >= 89 && snapshots[14] <= 90)
    assert(value > 97 && value < 99)
    model.update('complete', 100, 160_000)
    assert.equal(tick(model, value, 160_000, 160_500), 100)
})

test('30, 60 and 144 Hz follow the same elapsed-time curve', () => {
    const baseline = pipeline(60).snapshots
    for (const fps of [30, 144]) {
        pipeline(fps).snapshots.forEach((value, index) => {
            assert(Math.abs(value - baseline[index]) < 0.15, `refresh rate differs at snapshot ${index}`)
        })
    }
})

test('fast jobs complete immediately after confirmation; slow jobs stay bounded', () => {
    const fast = pipeline(60, 0.2)
    fast.model.update('complete', 100, 32_000)
    assert.equal(tick(fast.model, fast.value, 32_000, 33_000), 100)
    const slow = pipeline(30, 4)
    assert(slow.value < 100)
    slow.model.update('summary', 100, 640_000)
    assert(slow.model.target(3_000_000) <= 99, 'worker progress=100 alone is not success')
})

test('queue time does not advance analysis or consume the classification budget', () => {
    const model = new Progress()
    model.update('queued', 36, 0)
    assert.equal(tick(model, 10, 0, 600_000, 30), 10)
    model.update('classification', 36, 600_000)
    assert.equal(model.target(600_000), 10)
    assert(model.target(607_500) > 16 && model.target(607_500) < 18)
})

test('stale samples and long stalls do not regress progress or add more than two points', () => {
    const model = new Progress()
    model.update('segmentation', 71, 0)
    const value = tick(model, 20, 0, 10_000)
    assert(value > 55 && value <= 57)
    model.update('segmentation', 50, 10_000)
    assert.equal(model.raw, 71)
    assert(model.target(1_000_000) <= 57)
    assert(model.advance(value, 1_000_000) >= value)
})

test('resuming a background tab catches up smoothly and reset clears timing', () => {
    const model = new Progress()
    model.update('classification', 36, 0)
    let value = tick(model, 10, 0, 1000)
    model.lastFrameAt = null
    assert.equal(model.advance(value, 60_000), value)
    const next = model.advance(value, 60_016)
    assert(next > value && next - value < 1)
    model.reset()
    assert.equal(model.phase, 'idle')
    assert.equal(model.raw, 0)
    assert.equal(model.lastFrameAt, null)
})

test('upload progress depends on byte ratio, not the number of events', async () => {
    async function upload(fractions) {
        let xhr
        context.localStorage = { getItem: () => null }
        context.XMLHttpRequest = class {
            constructor() { this.upload = {}; xhr = this }
            open() {}
            send() {}
        }
        const state = { analysisProgress: { percent: 12, phase: 'upload' }, API_BASE: '' }
        const promise = app.methods.uploadTaskFiles.call(state, {})
        for (const fraction of fractions) xhr.upload.onprogress({ lengthComputable: true, loaded: fraction * 100, total: 100 })
        const halfway = state.analysisProgress.percent
        xhr.upload.onload()
        assert.equal(state.analysisProgress.percent, 36)
        xhr.status = 200
        xhr.responseText = '{}'
        xhr.onload()
        await promise
        return halfway
    }
    assert.equal(await upload([0.5]), 24)
    assert.equal(await upload([0.1, 0.2, 0.3, 0.4, 0.5]), 24)
})

test('clearing progress or requesting cancellation cancels the pending animation', () => {
    const canceled = []
    context.cancelAnimationFrame = (id) => canceled.push(id)
    const model = new Progress()
    model.update('segmentation', 71, 123)
    const state = { progressModel: model, progressAnimFrame: 7, progressMotionActive: true }
    state.stopProgressMotion = app.methods.stopProgressMotion.bind(state)
    app.watch.analysisProgress.handler.call(state, null)
    assert.equal(state.progressMotionActive, false)
    assert.equal(model.phase, 'idle')
    assert.equal(state.progressAnimFrame, null)
    state.progressAnimFrame = 8
    app.watch.analysisCancelled.call(state, true)
    assert.deepEqual(canceled, [7, 8])
})

test('compression progress weights bytes rather than assigning equal weight to unequal files', async () => {
    context.CompressionStream = CompressionStream
    context.File = File
    const state = { analysisProgress: { percent: 0 }, escapeHtml: value => value }
    await app.methods.gzipVolumeFileForUpload.call(state, new File([Buffer.alloc(8)], 'small.nii'), 'FLAIR', 0, 32)
    assert.equal(state.analysisProgress.percent, 3)
    await app.methods.gzipVolumeFileForUpload.call(state, new File([Buffer.alloc(24)], 'large.nii'), 'T1', 8, 32)
    assert.equal(state.analysisProgress.percent, 12)
})

test('polling timeout cleans up progress and the animation', async () => {
    let calls = 0
    context.Date = { now: () => (++calls === 1 ? 0 : 1_800_001) }
    context.fetch = async () => ({ ok: true })
    let stopped = 0
    const state = {
        analysisRunId: 1, API_BASE: '', authHeaders: {},
        startProgressMotion() {}, stopProgressMotion() { stopped++ },
    }
    await assert.rejects(app.methods.runAndGetResult.call(state, 'timeout'), /识别任务超时/)
    assert.equal(state.analysisPolling, false)
    assert.equal(state.analysisProgress, null)
    assert.equal(stopped, 1)
    delete context.Date
})

test('late responses from a previous run cannot clear or complete the new task', async () => {
    let resolveResponse
    context.Date = Date
    context.fetch = async url => url.endsWith('/run-async')
        ? { ok: true }
        : new Promise(resolve => { resolveResponse = resolve })
    const state = {
        analysisRunId: 1, API_BASE: '', authHeaders: {},
        startProgressMotion() {},
        stopProgressMotion() { throw new Error('must not stop the new task') },
        settleAndPresentResult() { throw new Error('must not present the old result') },
    }
    const oldRun = app.methods.runAndGetResult.call(state, 'old')
    await new Promise(setImmediate)
    state.analysisRunId = 2
    const newProgress = { percent: 12, phase: 'upload' }
    state.analysisProgress = newProgress
    resolveResponse({ ok: true, json: async () => ({ status: 'succeeded' }) })
    await oldRun
    assert.equal(state.analysisProgress, newProgress)
})

test('cancel request network errors allow the current progress animation to resume', async () => {
    context.fetch = async () => { throw new Error('network unavailable') }
    const state = { analysisRunId: 1, taskId: 'cancel', API_BASE: '', authHeaders: {}, escapeHtml: value => value }
    await app.methods.cancelCurrentAnalysis.call(state)
    assert.equal(state.analysisCancelled, false)
    assert.match(state.statusText, /network unavailable/)
})
