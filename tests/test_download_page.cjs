const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')

const source = readFileSync(path.join(__dirname, '../frontend/scripts/download.js'), 'utf8')
const repository = 'https://github.com/ckckh2023/BTIR-Client'
const release = (tag_name, published_at, extra = {}) => ({ tag_name, published_at, ...extra })

function runPage({ pages = [[]], fetchError = false, referrer = '', blockedStorage = false, hang = false } = {}) {
    const elements = new Map()
    for (const key of ['pc', 'harmony']) {
        elements.set(`[data-client="${key}"]`, { href: `${repository}/tree/${key === 'pc' ? 'PC' : 'Mobile-HarmonyOS'}` })
        elements.set(`[data-release-status="${key}"]`, { textContent: '' })
    }
    function control(extra = {}) {
        return { listeners: {}, attributes: {}, addEventListener(event, fn) { this.listeners[event] = fn }, setAttribute(name, value) { this.attributes[name] = value }, ...extra }
    }
    const theme = control()
    const back = control({ href: './index.html' })
    const root = { dataset: { theme: 'light' } }
    const storage = new Map()
    const windowListeners = {}
    const timers = []
    const requests = []
    let cleared = false
    let wentBack = 0
    const context = {
        AbortController, URL,
        document: { documentElement: root, referrer, getElementById: id => id === 'downloadTheme' ? theme : back, querySelector: selector => elements.get(selector) },
        location: { origin: 'http://localhost:8000' },
        history: { length: 2, back: () => wentBack++ },
        localStorage: { setItem: (key, value) => { if (blockedStorage) throw new Error('blocked'); storage.set(key, value) } },
        window: { addEventListener: (event, fn) => { windowListeners[event] = fn } },
        setTimeout: callback => { timers.push(callback); return 1 },
        clearTimeout: () => { cleared = true },
        fetch: async (url, options) => {
            requests.push({ url, options })
            if (hang) return new Promise((_, reject) => options.signal.addEventListener('abort', () => reject(new Error('aborted'))))
            if (fetchError) throw new Error('offline')
            const body = pages[requests.length - 1]
            return { ok: body !== 'http-error', json: async () => body }
        },
    }
    vm.runInNewContext(source, context)
    return { elements, theme, back, root, storage, windowListeners, timers, requests, cleared: () => cleared, wentBack: () => wentBack }
}

const settle = () => new Promise(resolve => setImmediate(resolve))

test('分别选择两类客户端最新的正式发布，不依赖返回顺序或发布分支', async () => {
    const page = runPage({ pages: [[
        release('HarmonyOS-Mobile-v26.1.1', '2026-10-17'),
        release('Windows-Linux-v1.0.1', '2026-10-16', { target_commitish: 'main', html_url: 'https://example.com' }),
        release('HarmonyOS-Mobile-v26.1.2', '2026-10-19', { target_commitish: 'main' }),
        release('Windows-Linux-v9.0.0', '2026-10-20', { prerelease: true }),
        release('Windows-Linux-v8.0.0', '2026-10-20', { draft: true }),
        release('Windows-Linux-v7.0.0', 'invalid'),
        release('Windows-Linux-v1.0.2/invalid', '2026-10-21'),
        null,
    ]] })
    await settle()
    assert.equal(page.elements.get('[data-client="pc"]').href, `${repository}/releases/tag/Windows-Linux-v1.0.1`)
    assert.equal(page.elements.get('[data-client="harmony"]').href, `${repository}/releases/tag/HarmonyOS-Mobile-v26.1.2`)
    assert.equal(page.requests[0].options.credentials, 'omit')
    assert.ok(page.cleared())
})

test('读取后续分页，支持平台更新频率不同与发布顺序变化', async () => {
    const first = Array.from({ length: 100 }, () => release('Windows-Linux-v1.0.0', '2026-10-10'))
    const page = runPage({ pages: [first, [release('HarmonyOS-Mobile-v26.1.2', '2026-10-19')]] })
    await settle()
    assert.equal(page.requests.length, 2)
    assert.ok(page.requests[1].url.endsWith('page=2'))
    assert.ok(page.elements.get('[data-client="harmony"]').href.endsWith('HarmonyOS-Mobile-v26.1.2'))
})

test('断网、限流、空发布列表和无效响应均保留可用的分支链接', async () => {
    for (const options of [{ fetchError: true }, { pages: ['http-error'] }, { pages: [{}] }, { pages: [[]] }]) {
        const page = runPage(options)
        await settle()
        assert.equal(page.elements.get('[data-client="pc"]').href, `${repository}/tree/PC`)
        assert.equal(page.elements.get('[data-client="harmony"]').href, `${repository}/tree/Mobile-HarmonyOS`)
        assert.ok(page.cleared())
    }
})

test('后续分页失败时保留静态入口', async () => {
    const page = runPage({ pages: [Array.from({ length: 100 }, () => release('Windows-Linux-v1.0.0', '2026-10-10')), 'http-error'] })
    await settle()
    assert.equal(page.elements.get('[data-client="pc"]').href, `${repository}/tree/PC`)
})

test('请求超时后中止查询并保留入口', async () => {
    const page = runPage({ hang: true })
    page.timers[0]()
    await settle()
    assert.ok(page.requests[0].options.signal.aborted)
    assert.ok(page.cleared())
    assert.equal(page.elements.get('[data-client="pc"]').href, `${repository}/tree/PC`)
})

test('主题切换与跨页同步只更新主题偏好', async () => {
    const page = runPage()
    page.theme.listeners.click()
    assert.equal(page.root.dataset.theme, 'dark')
    assert.equal(page.theme.attributes['aria-label'], '切换到浅色模式')
    assert.deepEqual([...page.storage], [['btir_theme', 'dark']])
    page.windowListeners.storage({ key: 'btir_theme', newValue: 'light' })
    assert.equal(page.root.dataset.theme, 'light')
    page.windowListeners.storage({ key: 'unrelated', newValue: 'dark' })
    assert.equal(page.root.dataset.theme, 'light')
    await settle()
})

test('浏览器禁止存储时仍可切换主题', async () => {
    const page = runPage({ blockedStorage: true })
    page.theme.listeners.click()
    assert.equal(page.root.dataset.theme, 'dark')
    await settle()
})

test('返回保留站内工作区历史，外站来源使用默认地址', async () => {
    const page = runPage({ referrer: 'http://localhost:8000/web/index.html?task=case-1' })
    let prevented = false
    page.back.listeners.click({ button: 0, preventDefault: () => { prevented = true } })
    assert.equal(page.wentBack(), 1)
    assert.ok(prevented)
    page.back.listeners.click({ button: 0, ctrlKey: true })
    assert.equal(page.wentBack(), 1)
    const foreign = runPage({ referrer: 'https://example.com/login/' })
    assert.equal(foreign.back.href, './index.html')
    assert.equal(foreign.back.listeners.click, undefined)
    await settle()
})
