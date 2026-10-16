const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync(path.join(__dirname, '../frontend/download.js'), 'utf8')
const repository = 'https://github.com/ckckh2023/BTIR-Client'

const release = (tag, publishedAt, overrides = {}) => ({
    tag_name: tag,
    published_at: publishedAt,
    draft: false,
    prerelease: false,
    target_commitish: 'main',
    ...overrides,
})

async function load(fetchResponse) {
    const elements = {
        '[data-client="pc"]': { href: `${repository}/tree/PC` },
        '[data-client="harmony"]': { href: `${repository}/tree/Mobile-HarmonyOS` },
        '[data-release-status="pc"]': {},
        '[data-release-status="harmony"]': {},
    }
    const requests = []
    vm.runInNewContext(source, {
        document: { querySelector: (selector) => elements[selector] },
        fetch: async (url, options) => {
            requests.push({ url, options })
            return fetchResponse(requests.length)
        },
        AbortController,
        setTimeout,
        clearTimeout,
    })
    await new Promise(setImmediate)
    return {
        pc: elements['[data-client="pc"]'],
        harmony: elements['[data-client="harmony"]'],
        pcStatus: elements['[data-release-status="pc"]'],
        harmonyStatus: elements['[data-release-status="harmony"]'],
        requests,
    }
}

const response = (releases) => ({ ok: true, json: async () => releases })

test('new versions select the latest publication for each client, regardless of API order', async () => {
    const result = await load(() => response([
        release('Windows-Linux-v1.0.1', '2026-10-16T00:00:00Z'),
        release('HarmonyOS-Mobile-v26.1.0', '2026-10-10T00:00:00Z'),
        release('Windows-Linux-v1.1.0', '2026-11-01T00:00:00Z', {
            html_url: 'https://example.com/untrusted',
            assets: [{ browser_download_url: `${repository}/releases/download/package.exe` }],
        }),
        release('HarmonyOS-Mobile-v27.0.0', '2026-11-02T00:00:00Z'),
    ]))
    assert.equal(result.pc.href, `${repository}/releases/tag/Windows-Linux-v1.1.0`)
    assert.equal(result.harmony.href, `${repository}/releases/tag/HarmonyOS-Mobile-v27.0.0`)
    assert.match(result.pcStatus.textContent, /Windows-Linux-v1\.1\.0/)
    assert.equal(result.requests[0].options.credentials, 'omit')
})

test('drafts, previews, unrelated tags and invalid publication dates cannot replace a stable release', async () => {
    const result = await load(() => response([
        release('Windows-Linux-v1.0.1', '2026-10-16T00:00:00Z'),
        release('Windows-Linux-v2.0.0', '2026-11-01T00:00:00Z', { draft: true }),
        release('Windows-Linux-v3.0.0', '2026-11-02T00:00:00Z', { prerelease: true }),
        release('Windows-Linux-v4.0.0-beta.1', '2026-11-03T00:00:00Z'),
        release('Other-Windows-Linux-v5.0.0', '2026-11-04T00:00:00Z'),
        release('Windows-Linux-v6.0.0', null),
        release('HarmonyOS-Mobile-v28.0.0-rc.1', '2026-11-05T00:00:00Z'),
        null,
    ]))
    assert.equal(result.pc.href, `${repository}/releases/tag/Windows-Linux-v1.0.1`)
    assert.equal(result.harmony.href, `${repository}/tree/Mobile-HarmonyOS`)
    assert.match(result.harmonyStatus.textContent, /暂无正式发布/)
})

test('pagination finds an infrequently updated client and compares publication dates across pages', async () => {
    const firstPage = Array.from({ length: 99 }, () => release('unrelated-v1.0.0', '2026-10-01T00:00:00Z'))
    firstPage.push(release('Windows-Linux-v1.0.1', '2026-10-16T00:00:00Z'))
    const result = await load((page) => response(page === 1 ? firstPage : [
        release('HarmonyOS-Mobile-v26.1.0', '2026-10-10T00:00:00Z'),
        release('Windows-Linux-v1.2.0', '2026-11-03T00:00:00Z'),
    ]))
    assert.equal(result.requests.length, 2)
    assert.match(result.requests[1].url, /per_page=100&page=2$/)
    assert.equal(result.pc.href, `${repository}/releases/tag/Windows-Linux-v1.2.0`)
    assert.equal(result.harmony.href, `${repository}/releases/tag/HarmonyOS-Mobile-v26.1.0`)
})

test('API failures and malformed responses retain usable branch links', async () => {
    for (const fetchResponse of [
        () => ({ ok: false, status: 403 }),
        () => response({ message: 'rate limited' }),
        () => { throw new Error('network unavailable') },
    ]) {
        const result = await load(fetchResponse)
        assert.equal(result.pc.href, `${repository}/tree/PC`)
        assert.equal(result.harmony.href, `${repository}/tree/Mobile-HarmonyOS`)
        assert.match(result.pcStatus.textContent, /暂未获取最新版本/)
    }
})
