(function () {
    'use strict'

    const repository = 'https://github.com/ckckh2023/BTIR-Client'
    const platforms = [
        { key: 'pc', tag: /^Windows-Linux-v\d+\.\d+\.\d+(?:\+[\da-z.-]+)?$/i },
        { key: 'harmony', tag: /^HarmonyOS-Mobile-v\d+\.\d+\.\d+(?:\+[\da-z.-]+)?$/i },
    ]

    function applyTheme(theme) {
        const dark = theme === 'dark'
        document.documentElement.dataset.theme = dark ? 'dark' : 'light'
        const button = document.getElementById('downloadTheme')
        const label = dark ? '切换到浅色模式' : '切换到深色模式'
        button.title = label
        button.setAttribute('aria-label', label)
    }

    applyTheme(document.documentElement.dataset.theme)
    document.getElementById('downloadTheme').addEventListener('click', () => {
        const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'
        applyTheme(theme)
        try { localStorage.setItem('btir_theme', theme) } catch { /* 存储不可用时仍可切换 */ }
    })
    window.addEventListener('storage', (event) => {
        if (event.key === 'btir_theme' || event.key === null) applyTheme(event.newValue)
    })

    try {
        const source = new URL(document.referrer)
        if (source.origin === location.origin && /\/(?:web|login)\/?(?:index\.html|login\.html)?$/.test(source.pathname)) {
            const back = document.getElementById('downloadBack')
            back.href = source.href
            back.addEventListener('click', (event) => {
                if (event.button !== 0 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return
                if (history.length > 1) {
                    event.preventDefault()
                    history.back()
                }
            })
        }
    } catch { /* 直接访问时使用页面中的默认返回地址 */ }

    async function updateReleaseLinks() {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 8000)
        const selected = new Map()
        try {
            for (let page = 1; ; page += 1) {
                const response = await fetch(`https://api.github.com/repos/ckckh2023/BTIR-Client/releases?per_page=100&page=${page}`, {
                    headers: { Accept: 'application/vnd.github+json' },
                    credentials: 'omit',
                    signal: controller.signal,
                })
                if (!response.ok) throw new Error('Release request failed')
                const releases = await response.json()
                if (!Array.isArray(releases)) throw new Error('Invalid releases')
                for (const release of releases) {
                    if (!release || release.draft || release.prerelease || typeof release.tag_name !== 'string') continue
                    const date = Date.parse(release.published_at)
                    if (!Number.isFinite(date)) continue
                    for (const platform of platforms) {
                        if (!platform.tag.test(release.tag_name)) continue
                        if (!selected.has(platform.key) || date > selected.get(platform.key).date) {
                            selected.set(platform.key, { date, tag: release.tag_name })
                        }
                    }
                }
                if (releases.length < 100) break
            }
            for (const platform of platforms) {
                const release = selected.get(platform.key)
                if (!release) continue
                document.querySelector(`[data-client="${platform.key}"]`).href = `${repository}/releases/tag/${encodeURIComponent(release.tag)}`
                document.querySelector(`[data-release-status="${platform.key}"]`).textContent = release.tag
            }
        } catch { /* 请求失败时保留静态 GitHub 分支链接 */ }
        finally { clearTimeout(timeout) }
    }

    updateReleaseLinks()
})()
