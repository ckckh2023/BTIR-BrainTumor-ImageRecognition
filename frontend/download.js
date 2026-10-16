(function () {
    const repository = 'https://github.com/ckckh2023/BTIR-Client'
    const releasesApi = 'https://api.github.com/repos/ckckh2023/BTIR-Client/releases'
    // 只匹配对应平台的正式版本标签，不绑定具体版本号或 target_commitish。
    // 现有发布的 target_commitish 都是 main，无法用它区分客户端。
    const clients = [
        { key: 'pc', tagPattern: /^Windows-Linux-v\d+\.\d+\.\d+(?:\+[0-9a-z.-]+)?$/i },
        { key: 'harmony', tagPattern: /^HarmonyOS-Mobile-v\d+\.\d+\.\d+(?:\+[0-9a-z.-]+)?$/i },
    ].map((client) => ({
        ...client,
        link: document.querySelector(`[data-client="${client.key}"]`),
        status: document.querySelector(`[data-release-status="${client.key}"]`),
        latest: null,
    }))

    const loadLatestReleases = async () => {
        const controller = new AbortController()
        const timeout = setTimeout(() => controller.abort(), 8000)
        clients.forEach((client) => { client.status.textContent = '正在检查最新版本…' })
        try {
            // 分页读取，避免其中一个客户端较久未更新，被另一端的发布挤出首页。
            for (let page = 1; ; page += 1) {
                const response = await fetch(`${releasesApi}?per_page=100&page=${page}`, {
                    headers: { Accept: 'application/vnd.github+json' },
                    cache: 'no-cache',
                    credentials: 'omit',
                    signal: controller.signal,
                })
                if (!response.ok) throw new Error(`GitHub releases: ${response.status}`)
                const releases = await response.json()
                if (!Array.isArray(releases)) throw new Error('Invalid GitHub releases response')
                for (const release of releases) {
                    if (!release || release.draft || release.prerelease || typeof release.tag_name !== 'string') continue
                    const publishedAt = Date.parse(release.published_at)
                    if (!Number.isFinite(publishedAt)) continue
                    for (const client of clients) {
                        if (!client.tagPattern.test(release.tag_name)) continue
                        if (!client.latest || publishedAt > client.latest.publishedAt) {
                            client.latest = { tag: release.tag_name, publishedAt }
                        }
                    }
                }
                if (releases.length < 100) break
            }
            clients.forEach((client) => {
                if (client.latest) {
                    // 自行构造发布页 URL，始终打开 GitHub 页面，不使用附件下载地址。
                    client.link.href = `${repository}/releases/tag/${encodeURIComponent(client.latest.tag)}`
                    client.status.textContent = `最新发布：${client.latest.tag}`
                } else {
                    client.status.textContent = '暂无正式发布，可前往客户端分支查看。'
                }
            })
        } catch (e) {
            clients.forEach((client) => {
                client.status.textContent = '暂未获取最新版本，可前往客户端分支查看。'
            })
        } finally {
            clearTimeout(timeout)
        }
    }

    loadLatestReleases()
})()
