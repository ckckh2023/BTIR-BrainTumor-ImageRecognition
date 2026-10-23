const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')

const source = readFileSync(path.join(__dirname, '../frontend/scripts/app.js'), 'utf8')

function fixture() {
    let options
    const storage = () => {
        const values = new Map()
        return {
            getItem: key => values.get(key) ?? null,
            setItem: (key, value) => values.set(key, value),
            removeItem: key => values.delete(key),
        }
    }
    const requests = [], delays = [], frames = new Map()
    let frameId = 0
    class XHR {
        constructor() { this.upload = {}; requests.push(this) }
        open() {}
        setRequestHeader() {}
        send() {}
    }
    const context = {
        Vue: { createApp(value) { options = value; return { mount() {} } } },
        window: { location: { href: 'http://localhost/web/index.html' } },
        localStorage: storage(), sessionStorage: storage(), URL,
        XMLHttpRequest: XHR,
        performance: { now: () => 0 },
        setTimeout(fn, delay) { delays.push(delay); queueMicrotask(fn) },
        requestAnimationFrame(fn) { frames.set(++frameId, fn); return frameId },
        cancelAnimationFrame(id) { frames.delete(id) },
    }
    vm.runInNewContext(source, context)
    const state = options.data()
    for (const [name, method] of Object.entries(options.methods)) state[name] = method.bind(state)
    for (const [name, getter] of Object.entries(options.computed)) {
        Object.defineProperty(state, name, { get: () => getter.call(state) })
    }
    const phases = () => Array.from(state.analysisPhases, phase => phase.state)
    const report = (percent, status = 'running', stage = '3D 分割推理中', phase) => {
        state.taskId = 'test-task'
        state.analysisPolling = true
        state.applyTaskProgress({ progress: percent, progress_stage: stage, status, progress_phase: phase })
    }
    const frame = now => {
        const callbacks = Array.from(frames.values())
        frames.clear()
        for (const fn of callbacks) fn(now)
    }
    return { state, context, requests, delays, phases, report, frames, frame }
}

test('显示整数百分比，内部保留服务端精度，不自行推进', () => {
    const f = fixture()
    for (const percent of [0, 36, 44, 63.4, 80, 98, 99, 99.9, 100]) {
        f.report(percent)
        assert.equal(f.state.displayProgress, Math.floor(percent))
        assert.equal(f.state.analysisProgress.percent, percent)
        assert.equal(f.state.analysisProgressValue, percent)
        assert.equal(f.state.analysisProgressLabel, '3D 分割推理中')
    }
    f.report(63)
    assert.equal(f.state.displayProgress, 63)
    assert.equal(f.delays.length, 0)
})

test('兼容旧服务端的百分比，运行中达到 100 也不提前标记完成', () => {
    const f = fixture()
    for (const [percent, expected] of [
        [36, ['active', 'pending', 'pending']],
        [43, ['active', 'pending', 'pending']],
        [44, ['done', 'active', 'pending']],
        [98, ['done', 'active', 'pending']],
        [99, ['done', 'done', 'active']],
        [100, ['done', 'done', 'active']],
    ]) {
        f.report(percent)
        assert.deepEqual(f.phases(), expected)
    }
})

test('同一识别中随有效更新节奏由快变慢、再变快，保持已确认目标', () => {
    const f = fixture()
    let now = 0, percent = 0
    f.context.performance = { now: () => now }
    const advance = interval => {
        now += interval
        percent += 2
        f.report(percent, 'running', '分割推理中', 'segmentation')
        assert.equal(f.state.analysisProgressValue, percent)
        assert.ok(f.state.analysisProgressTransitionMs >= 500 && f.state.analysisProgressTransitionMs <= 3000)
        return f.state.analysisProgressTransitionMs
    }
    f.report(0, 'running', '分割推理中', 'segmentation')
    for (let index = 0; index < 6; index++) advance(500)
    const fast = f.state.analysisProgressTransitionMs
    assert.ok(fast <= 900)
    for (let index = 0; index < 4; index++) advance(4000)
    const slow = f.state.analysisProgressTransitionMs
    assert.ok(slow > fast + 1000)
    for (let index = 0; index < 7; index++) advance(500)
    assert.ok(f.state.analysisProgressTransitionMs < slow - 1000)
    assert.ok(f.state.analysisProgressTransitionMs <= 1000)
    assert.equal(f.delays.length, 0)
})

test('条宽和整数标签同步缓动，连续追赶且始终落后于确认值', () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.report(20)
    now = 500
    f.report(30)
    const duration = f.state.analysisProgressTransitionMs
    assert.equal(f.state.analysisProgressWidth, 20)
    let previous = 20
    for (let index = 1; index <= 4; index++) {
        now += 100
        f.frame(now)
        const width = f.state.analysisProgressWidth
        assert.ok(width > previous && width < 30)
        assert.equal(f.state.displayProgress, Math.floor(width))
        previous = width
    }
    const frameId = f.state._analysisProgressFrame
    const velocity = f.state.analysisProgressTiming.velocity
    f.report(30)
    assert.equal(f.state._analysisProgressFrame, frameId)
    assert.equal(f.state.analysisProgressTransitionMs, duration)
    now += 100
    f.report(40)
    assert.equal(f.state._analysisProgressFrame, frameId, '新目标不重启动画')
    assert.equal(f.state.analysisProgressWidth, previous, '新目标不跳动')
    assert.equal(f.state.analysisProgressTiming.velocity, velocity, '新目标沿用当前速度')
    f.frame(now)
    assert.ok(f.state.analysisProgressWidth > previous && f.state.analysisProgressWidth < 40)
    now += 60000
    f.frame(now)
    const held = f.state.analysisProgressWidth
    assert.ok(held > previous && held < 40, '长时间没有新值时保留余量，不超调')
    f.frame(now + 1000)
    assert.ok(f.state.analysisProgressWidth > held && f.state.analysisProgressWidth < 40)
})

test('缓动复用自适应时长，按实际时间计算，不依赖帧率', () => {
    const simulate = frameMs => {
        const f = fixture()
        let now = 0
        f.context.performance = { now: () => now }
        f.report(20)
        now = 2000
        f.report(40)
        const duration = f.state.analysisProgressTransitionMs
        for (let elapsed = frameMs; elapsed <= duration / 2; elapsed += frameMs) f.frame(now + elapsed)
        f.frame(now + duration / 2)
        const expected = 40 - 20 * (1 + 2 / 3) * Math.exp(-2 / 3)
        assert.ok(Math.abs(f.state.analysisProgressWidth - expected) < 1e-9)
        return f.state.analysisProgressWidth
    }
    assert.ok(Math.abs(simulate(16) - simulate(100)) < 1e-9)
})

test('快、中、慢服务器的阶段停更期间仍保留可移动余量', () => {
    const updates = [
        [0, 0], [500, 3], [1000, 7], [1500, 12], [2000, 20], [2500, 20],
        [3000, 22.4], [3500, 29.6], [6500, 32.2], [7000, 40], [7500, 52],
        [8000, 66], [8500, 80], [9000, 81.4], [15000, 92.6], [15500, 94],
        [16000, 97], [16500, 99.5],
    ]
    for (const scale of [0.5, 1, 2]) {
        const f = fixture()
        let now = 0, index = 0, previous = 0, slowMs = 0, longestSlowMs = 0
        f.context.performance = { now: () => now }
        for (now = 0; now <= 17000 * scale; now += 20) {
            while (index < updates.length && now >= updates[index][0] * scale) {
                f.report(updates[index++][1])
            }
            if (now % (500 * scale) === 0 && index) f.report(updates[index - 1][1])
            f.frame(now)
            const displayed = f.state.analysisProgressWidth
            const confirmed = f.state.analysisProgressValue
            assert.ok(displayed >= previous && displayed <= confirmed)
            assert.equal(f.state.displayProgress, Math.floor(displayed))
            const speed = (displayed - previous) / 20 * 1000
            slowMs = confirmed > 0 && speed < 0.1 ? slowMs + 20 : 0
            longestSlowMs = Math.max(longestSlowMs, slowMs)
            previous = displayed
        }
        assert.ok(longestSlowMs <= 100, `${scale} 倍时间序列接近静止 ${longestSlowMs}ms`)
        assert.ok(previous > 85, '保持余量，同时避免积累过多显示延迟')
    }
})

test('收到成功结果后按剩余差值平滑收齐，数字和条宽同步且不额外久等', async () => {
    const f = fixture()
    let now = 0, release
    f.context.performance = { now: () => now }
    f.context.setTimeout = (fn, delay) => { f.delays.push(delay); release = fn }
    f.report(85)
    let presented = false
    f.state.presentTaskResult = () => { presented = true }
    const pending = f.state.settleAndPresentResult({ status: 'succeeded' })
    assert.equal(f.state.analysisProgressValue, 100)
    assert.equal(f.state.displayProgress, 85)
    assert.equal(presented, false)
    let previous = 85
    for (now = 100; now <= 600; now += 100) {
        f.frame(now)
        const displayed = f.state.analysisProgressWidth
        assert.ok(displayed > previous && displayed <= 100)
        assert.equal(f.state.displayProgress, Math.floor(displayed))
        previous = displayed
    }
    assert.equal(previous, 100)
    assert.ok(f.delays[0] >= 600 && f.delays[0] <= 850)
    release()
    await pending
    assert.equal(presented, true)
    assert.equal(f.frames.size, 0)
})

test('重试和清理取消旧动画，迟到的帧不会污染新任务', () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.report(20)
    now = 500
    f.report(40)
    const stale = Array.from(f.frames.values())[0]
    now = 600
    f.report(5)
    assert.equal(f.frames.size, 0)
    assert.equal(f.state.analysisProgressWidth, 5)
    stale(700)
    assert.equal(f.state.analysisProgressWidth, 5)
    now = 1100
    f.report(10)
    const newFrameId = f.state._analysisProgressFrame
    stale(1200)
    assert.equal(f.state._analysisProgressFrame, newFrameId)
    assert.equal(f.frames.size, 1, '旧帧不能打断新动画')
    f.state.resetAnalysisProgressTiming()
    assert.equal(f.frames.size, 0)
    assert.equal(f.state.analysisProgressDisplayed, null)
})

test('减少动态效果时直接跟随服务端，完成时取消追赶并显示确认的 100', async () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.context.window.matchMedia = () => ({ matches: true })
    f.report(20)
    now = 500
    f.report(40)
    assert.equal(f.state.analysisProgressWidth, 40)
    assert.equal(f.frames.size, 0)
    f.context.window.matchMedia = () => ({ matches: false })
    now = 1000
    f.report(60)
    assert.equal(f.frames.size, 1)
    f.state.presentTaskResult = () => {}
    const settled = f.state.settleAndPresentResult({})
    assert.equal(f.frames.size, 1)
    assert.equal(f.state.displayProgress, 40)
    f.frame(now + 800)
    assert.equal(f.state.displayProgress, 100)
    await settled
})

test('重复百分比不刷新采样时间，下一次更新包含真实等待时间', () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.report(20, 'running', '分割推理中', 'segmentation')
    now = 500
    f.report(22, 'running', '分割推理中', 'segmentation')
    const duration = f.state.analysisProgressTransitionMs
    for (now = 1000; now <= 3500; now += 500) {
        f.report(22, 'running', '分割推理中', 'segmentation')
        assert.equal(f.state.analysisProgressTransitionMs, duration)
        assert.equal(f.state.analysisProgressTiming.intervalMs, 500)
        assert.equal(f.state.analysisProgressTiming.rate, 2 / 500)
        assert.equal(f.state.analysisProgressTiming.changedAt, 500)
    }
    f.report(24, 'running', '分割推理中', 'segmentation')
    assert.ok(f.state.analysisProgressTransitionMs > duration + 500)
    assert.equal(f.state.analysisProgressTiming.intervalMs, 1550)
})

test('服务源、任务、重试、回退或缺少有效进度都会重置临时统计', () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.state.API_BASE = 'https://source-a'
    f.state.taskId = 'task-a'
    const report = (percent, attempt = 1, status = 'running') => f.state.applyTaskProgress({
        progress: percent, status, progress_stage: '分割推理中', progress_phase: 'segmentation', job: { attempt },
    })
    const train = () => { report(0); now += 4000; report(10); assert.equal(f.state.analysisProgressTransitionMs, 3000) }
    const fresh = () => {
        assert.equal(f.state.analysisProgressTiming.intervalMs, null)
        assert.equal(f.state.analysisProgressTiming.rate, null)
        assert.equal(f.state.analysisProgressTransitionMs, 0)
    }
    train()
    f.state.API_BASE = 'https://source-b'
    report(12);fresh()
    assert.equal(f.state.analysisProgressTiming.source, 'https://source-b')
    now += 4000;report(14)
    f.state.taskId = 'task-b'
    report(15);fresh()
    assert.equal(f.state.analysisProgressTiming.taskId, 'task-b')
    now += 4000;report(16)
    report(18, 2);fresh()
    assert.equal(f.state.analysisProgressTiming.attempt, 2)
    now += 4000;report(20, 2)
    report(1, 2);fresh()
    report(99, 2, 'queued')
    assert.equal(f.state.analysisProgressTiming, null)
    report(0, 3);fresh()
    report(undefined, 3)
    assert.equal(f.state.analysisProgressTiming, null)
    report(1, 3);fresh()
    report(2, 3, 'cancel_requested')
    assert.equal(f.state.analysisProgressTiming, null)
})

test('已对齐的阶段边界仍受服务端确认约束，进度未知时等待', () => {
    const f = fixture()
    f.report(44, 'running', '分类结果已生成', 'classification')
    assert.deepEqual(f.phases(), ['active', 'pending', 'pending'])
    f.report(44, 'running', '正在加载分割模型', 'segmentation')
    assert.deepEqual(f.phases(), ['done', 'active', 'pending'])
    f.report(99, 'running', '正在保存分割结果', 'segmentation')
    assert.deepEqual(f.phases(), ['done', 'active', 'pending'])
    f.report(99, 'running', '正在生成综合分析', 'summary')
    assert.deepEqual(f.phases(), ['done', 'done', 'active'])
    f.report(null, 'running', '正在生成综合分析', 'summary')
    assert.deepEqual(f.phases(), ['pending', 'pending', 'pending'])
    f.report(99, 'queued', '旧进度', 'summary')
    assert.deepEqual(f.phases(), ['pending', 'pending', 'pending'])
    f.report(100, 'succeeded')
    assert.deepEqual(f.phases(), ['done', 'done', 'done'])
})

test('阶段和具体说明跟随前端条宽，不因服务器提前进入下一阶段而跳变', () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.state.inferenceProgressRanges = { classification: [0, 20], segmentation: [20, 80], summary: [80, 100] }
    f.report(10, 'running', '正在分类切片', 'classification')
    now = 500
    f.report(20, 'running', '分类结果已生成', 'classification')
    now = 1000
    f.report(32, 'running', '分割窗口 1/10', 'segmentation')
    now = 1500
    f.report(60, 'running', '分割窗口 6/10', 'segmentation')
    now = 2000
    f.report(81.4, 'running', '正在生成综合分析', 'summary')
    for (const [percent, phases, label] of [
        [19.99, ['active', 'pending', 'pending'], '正在分类切片'],
        [20, ['done', 'active', 'pending'], '3D 分割推理中...'],
        [40, ['done', 'active', 'pending'], '分割窗口 1/10'],
        [79.99, ['done', 'active', 'pending'], '分割窗口 6/10'],
        [80, ['done', 'done', 'active'], '正在生成综合分析...'],
        [81.4, ['done', 'done', 'active'], '正在生成综合分析'],
    ]) {
        f.state.analysisProgressDisplayed = percent
        assert.deepEqual(f.phases(), phases)
        assert.equal(f.state.analysisProgressLabel, label)
    }
})

test('同一百分比的阶段更新等前端到达才生效，重试清理旧说明', () => {
    const f = fixture()
    let now = 0
    f.context.performance = { now: () => now }
    f.state.inferenceProgressRanges = { classification: [0, 20], segmentation: [20, 80], summary: [80, 100] }
    f.report(10, 'running', '正在分类切片', 'classification')
    now = 500
    f.report(20, 'running', '分类结果已生成', 'classification')
    f.report(20, 'running', '正在加载分割模型', 'segmentation')
    for (let index = 0; index < 10; index++) f.report(20, 'running', '正在加载分割模型', 'segmentation')
    assert.equal(f.state.analysisProgressHistory.length, 3)
    f.state.analysisProgressDisplayed = 19
    assert.equal(f.state.analysisProgressLabel, '正在分类切片')
    assert.deepEqual(f.phases(), ['active', 'pending', 'pending'])
    f.state.analysisProgressDisplayed = 20
    assert.equal(f.state.analysisProgressLabel, '正在加载分割模型')
    assert.deepEqual(f.phases(), ['done', 'active', 'pending'])
    f.report(20, 'running', '正在加载分割模型', 'segmentation')
    assert.equal(f.state.analysisProgressHistory.length, 1, '到达后的旧检查点被清理')
    f.report(0, 'running', '重新分类中', 'classification')
    assert.equal(f.state.analysisProgressHistory.length, 1)
    assert.equal(f.state.analysisProgressLabel, '重新分类中')
    f.report(0, 'queued')
    assert.equal(f.state.analysisProgressHistory.length, 0)
    assert.equal(f.state.analysisProgressLabel, '任务排队中...')
})

test('成功收尾期间阶段与说明继续跟随条宽，到 100 才全部完成', async () => {
    const f = fixture()
    let now = 0, release
    f.context.performance = { now: () => now }
    f.context.setTimeout = fn => { release = fn }
    f.state.inferenceProgressRanges = { classification: [0, 20], segmentation: [20, 80], summary: [80, 100] }
    f.report(10, 'running', '正在分类切片', 'classification')
    now = 500
    f.report(60, 'running', '分割窗口 6/10', 'segmentation')
    now = 1000
    f.report(81.4, 'running', '正在生成综合分析', 'summary')
    f.state.analysisProgressDisplayed = 70
    f.state.presentTaskResult = () => {}
    const pending = f.state.settleAndPresentResult({ status: 'succeeded' })
    assert.deepEqual(f.phases(), ['done', 'active', 'pending'])
    assert.equal(f.state.analysisProgressLabel, '分割窗口 6/10')
    assert.ok(!f.state.statusText.includes('分析完成'))
    f.frame(now + 400)
    assert.deepEqual(f.phases(), ['done', 'done', 'active'])
    assert.ok(!f.state.analysisProgressLabel.includes('分析完成'))
    f.frame(now + 800)
    assert.deepEqual(f.phases(), ['done', 'done', 'done'])
    assert.equal(f.state.analysisProgressLabel, '3D 分割与综合分析完成')
    assert.ok(f.state.statusText.includes('分析完成'))
    release()
    await pending
})

test('排队时不提前激活分类，也不沿用重试前的旧进度', () => {
    const f = fixture()
    f.report(99)
    f.report(99, 'queued')
    assert.equal(f.state.displayProgress, null)
    assert.equal(f.state.analysisProgressLabel, '任务排队中...')
    assert.deepEqual(f.phases(), ['pending', 'pending', 'pending'])
    f.report(36)
    assert.equal(f.state.displayProgress, 36)
    assert.deepEqual(f.phases(), ['active', 'pending', 'pending'])
})

test('缺少或无效百分比时显示等待状态，不保留旧百分比', () => {
    const f = fixture()
    for (const percent of [null, undefined, NaN, Infinity, '', '60', false]) {
        f.report(80)
        f.report(percent, 'running', '正在准备推理...')
        assert.equal(f.state.displayProgress, null)
        assert.equal(f.state.analysisProgressLabel, '正在准备推理...')
        assert.deepEqual(f.phases(), ['pending', 'pending', 'pending'])
    }
    f.report(-1)
    assert.equal(f.state.displayProgress, 0)
    f.report(101)
    assert.equal(f.state.displayProgress, 100)
})

test('上传只显示真实传输百分比，校验结束前不显示推理条', async () => {
    const f = fixture()
    f.state.analysisProgress = { percent: 12, stage: '旧进度' }
    const pending = f.state.uploadTaskFiles({})
    const xhr = f.requests[0]
    for (const percent of [25, 50, 50, 75, 100]) {
        xhr.upload.onprogress({ lengthComputable: true, total: 100, loaded: percent })
        assert.equal(f.state.displayProgress, null)
        assert.equal(f.state.analysisProgress, null)
        assert.ok(f.state.statusText.endsWith(` ${percent}%`))
    }
    xhr.upload.onload()
    assert.ok(f.state.statusText.includes('正在校验上传数据'))
    assert.equal(f.state.analysisProgress, null)
    xhr.status = 201
    xhr.responseText = '{"task_id":"created-task"}'
    xhr.onload()
    assert.equal((await pending).task_id, 'created-task')
})

test('未知上传长度不虚构百分比，也不显示推理进度', async () => {
    const f = fixture()
    const pending = f.state.uploadTaskFiles({})
    f.requests[0].upload.onprogress({ lengthComputable: false })
    assert.equal(f.state.analysisProgress, null)
    assert.ok(f.state.statusText.includes('正在上传数据'))
    assert.ok(!f.state.statusText.includes('%'))
    f.requests[0].onerror()
    await assert.rejects(pending, /网络错误/)
})

test('从服务端读取 20/60/20 分配，阶段与分隔点使用同一份配置', async () => {
    const f = fixture()
    const ranges = { classification: [0, 20], segmentation: [20, 80], summary: [80, 100] }
    f.context.fetch = async () => ({ ok: true, json: async () => ({ inference_progress_ranges: ranges }) })
    await f.state.loadFrontendRuntimeConfig()
    assert.deepEqual(Array.from(f.state.analysisProgressStops), [20, 80])
    for (const [percent, expected] of [
        [0, ['active', 'pending', 'pending']],
        [19.9, ['active', 'pending', 'pending']],
        [20, ['done', 'active', 'pending']],
        [79.9, ['done', 'active', 'pending']],
        [80, ['done', 'done', 'active']],
        [99.9, ['done', 'done', 'active']],
    ]) {
        f.report(percent)
        assert.deepEqual(f.phases(), expected)
    }
    f.context.fetch = async () => ({ ok: true, json: async () => ({ inference_progress_ranges: {
        classification: [0, 20], segmentation: [19, 80], summary: [80, 100],
    } }) })
    await f.state.loadFrontendRuntimeConfig()
    assert.equal(f.state.inferenceProgressRanges, ranges)
})

test('完整轮询直接采用服务器进度，成功后才显示完成并呈现结果', async () => {
    const f = fixture()
    const responses = [
        { status: 'queued', progress: null },
        { status: 'running', progress: 36, progress_stage: '3D 分类推理中' },
        { status: 'running', progress: 44, progress_stage: '3D 分割推理中' },
        { status: 'running', progress: 73, progress_stage: '3D 分割推理中' },
        { status: 'running', progress: 99, progress_stage: '正在生成综合分析' },
        { status: 'succeeded', task_id: 'test-task' },
    ]
    f.context.fetch = async (_url, init) => ({
        ok: true, json: async () => init?.method === 'POST' ? {} : responses.shift(),
    })
    const observed = []
    const apply = f.state.applyTaskProgress
    f.state.applyTaskProgress = data => { apply(data); observed.push(f.state.displayProgress) }
    let result
    f.state.presentTaskResult = data => { result = data }
    await f.state.runAndGetResult('test-task')
    assert.deepEqual(observed, [null, 36, 44, 73, 99])
    assert.equal(result.status, 'succeeded')
    assert.equal(f.state.analysisProgress, null)
    assert.equal(f.state.analysisPolling, false)
    assert.equal(f.state.analysisProgressTiming, null)
    assert.equal(f.delays.at(-1), 400)
})

test('服务端失败或取消后清除进度，不显示完成', async () => {
    for (const status of ['failed', 'canceled']) {
        const f = fixture()
        f.report(73)
        f.context.fetch = async () => ({ ok: true, json: async () => ({ status, error: { message: '推理失败' } }) })
        f.state.presentTaskResult = () => { throw new Error('不应呈现失败结果') }
        const pending = f.state.runAndGetResult('test-task')
        if (status === 'failed') await assert.rejects(pending, /推理失败/)
        else await pending
        assert.equal(f.state.analysisProgress, null)
        assert.equal(f.state.analysisPolling, false)
        assert.equal(f.state.analysisProgressTiming, null)
    }
})

test('取消期间返回的旧响应不会再把进度推进到完成', async () => {
    const f = fixture()
    let finishResponse
    const response = new Promise(resolve => { finishResponse = resolve })
    f.context.fetch = async (_url, init) => ({
        ok: true, json: async () => init?.method === 'POST' ? {} : response,
    })
    f.state.presentTaskResult = () => { throw new Error('取消后不应呈现结果') }
    const pending = f.state.runAndGetResult('test-task')
    await new Promise(resolve => setImmediate(resolve))
    f.state.analysisCancelled = true
    finishResponse({ status: 'succeeded' })
    await pending
    assert.equal(f.state.analysisProgress, null)
    assert.equal(f.state.analysisPolling, false)
})

test('长任务运行时保持 500ms 刷新，只有排队状态放慢轮询', async () => {
    for (const [status, expectedDelay] of [['running', 500], ['queued', 3000]]) {
        const f = fixture()
        let now = 0, polls = 0
        f.context.Date = class extends Date { static now() { return now } }
        f.context.fetch = async (_url, init) => {
            if (init?.method === 'POST') return { ok: true }
            assert.equal(init.cache, 'no-store')
            now = 70000
            return { ok: true, json: async () => ++polls <= 2
                ? { status, progress: 60, progress_stage: '3D 分割推理中' }
                : { status: 'succeeded' } }
        }
        f.state.presentTaskResult = () => {}
        await f.state.runAndGetResult('test-task')
        assert.equal(f.delays[0], 0)
        assert.equal(f.delays[1], expectedDelay)
    }
})

test('同步周期扣除网络耗时，避免在响应之后再多等 500ms', async () => {
    for (const [requestMs, expectedDelay] of [[200, 300], [800, 0]]) {
        const f = fixture()
        let now = 0, polls = 0
        f.context.Date = class extends Date { static now() { return now } }
        f.context.fetch = async (_url, init) => {
            if (init?.method === 'POST') return { ok: true }
            now += requestMs
            return { ok: true, json: async () => ++polls === 1
                ? { status: 'running', progress: 63.375, progress_phase: 'segmentation' }
                : { status: 'succeeded' } }
        }
        f.state.presentTaskResult = () => {}
        await f.state.runAndGetResult('test-task')
        assert.equal(f.delays[0], expectedDelay)
    }
})

test('旧任务晚返回不会覆盖或清空正在适应的新任务', async () => {
    const f = fixture()
    let finishOld, finishNew, newPolls = 0
    const oldResponse = new Promise(resolve => { finishOld = resolve })
    const newResponse = new Promise(resolve => { finishNew = resolve })
    f.context.fetch = async (url, init) => {
        if (init?.method === 'POST') return { ok: true }
        return { ok: true, json: async () => url.includes('/task-old') ? oldResponse
            : ++newPolls === 1 ? { status: 'running', progress: 10, progress_phase: 'classification' } : newResponse }
    }
    let presented
    f.state.presentTaskResult = result => { presented = result.task_id }
    const old = f.state.runAndGetResult('task-old')
    await new Promise(resolve => setImmediate(resolve))
    const fresh = f.state.runAndGetResult('task-new')
    await new Promise(resolve => setImmediate(resolve))
    finishOld({ status: 'succeeded', task_id: 'task-old' })
    await old
    assert.equal(presented, undefined)
    assert.equal(f.state.analysisPolling, true)
    assert.equal(f.state.analysisProgressValue, 10)
    assert.equal(f.state.analysisProgressTiming.taskId, 'task-new')
    finishNew({ status: 'succeeded', task_id: 'task-new' })
    await fresh
    assert.equal(presented, 'task-new')
    assert.equal(f.state.analysisProgressTiming, null)
})

test('服务源切换后丢弃原服务的响应并释放当前统计', async () => {
    const f = fixture()
    f.state.API_BASE = 'https://source-a'
    let finishResponse
    const pendingResponse = new Promise(resolve => { finishResponse = resolve })
    f.context.fetch = async (url, init) => {
        assert.ok(url.startsWith('https://source-a/'))
        return { ok: true, json: async () => init?.method === 'POST' ? {} : pendingResponse }
    }
    f.state.presentTaskResult = () => { throw new Error('不能展示旧服务的结果') }
    const pending = f.state.runAndGetResult('test-task')
    await new Promise(resolve => setImmediate(resolve))
    f.state.API_BASE = 'https://source-b'
    finishResponse({ status: 'succeeded' })
    await pending
    assert.equal(f.state.analysisProgress, null)
    assert.equal(f.state.analysisProgressTiming, null)
    assert.equal(f.state.analysisPolling, false)
})

test('完成过渡期间换任务，旧结果也不会在延时结束后呈现', async () => {
    const f = fixture()
    let completeTransition, finishNew
    const newResponse = new Promise(resolve => { finishNew = resolve })
    f.context.setTimeout = (fn, delay) => {
        if (delay >= 400 && !completeTransition) completeTransition = fn
        else queueMicrotask(fn)
    }
    f.context.fetch = async (url, init) => ({ ok: true, json: async () => init?.method === 'POST' ? {}
        : url.includes('/task-old') ? { status: 'succeeded', task_id: 'task-old' } : newResponse })
    const presented = []
    f.state.presentTaskResult = result => presented.push(result.task_id)
    const old = f.state.runAndGetResult('task-old')
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(f.state.analysisProgressValue, 100)
    const fresh = f.state.runAndGetResult('task-new')
    await new Promise(resolve => setImmediate(resolve))
    completeTransition()
    await old
    assert.deepEqual(presented, [])
    assert.equal(f.state.analysisPolling, true)
    finishNew({ status: 'succeeded', task_id: 'task-new' })
    await fresh
    assert.deepEqual(presented, ['task-new'])
    assert.equal(f.state.analysisProgressTiming, null)
})

test('发起取消即清空统计，迟到的取消响应不会清掉新任务', async () => {
    const f = fixture()
    f.report(20, 'running', '分割推理中', 'segmentation')
    assert.ok(f.state.analysisProgressTiming)
    let finishCancel
    const cancelResponse = new Promise(resolve => { finishCancel = resolve })
    f.context.fetch = async () => cancelResponse
    const pending = f.state.cancelCurrentAnalysis()
    assert.equal(f.state.analysisProgressTiming, null)
    f.state.analysisRunSequence += 1
    f.state.analysisCancelled = false
    f.state.taskId = 'task-new'
    f.state.applyTaskProgress({ status: 'running', progress: 10, progress_phase: 'classification' })
    finishCancel({ ok: true, json: async () => ({ status: 'canceled' }) })
    await pending
    assert.equal(f.state.taskId, 'task-new')
    assert.equal(f.state.analysisProgressValue, 10)
    assert.equal(f.state.analysisProgressTiming.taskId, 'task-new')
})
