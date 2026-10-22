function renderMarkdown(text) {
    const escapeHtml = (value) => String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
    // 相对图片路径以 /assets/ 为基准（guide.md 存放在 assets 目录下）
    const resolveAsset = (src) => /^(?:[a-z][a-z0-9+.-]*:|\/|data:)/i.test(src)
        ? src
        : `/assets/${src}`
    const inline = (value) => escapeHtml(value)
        .replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, src) =>
            `<img src="${resolveAsset(src)}" alt="${alt}" loading="lazy">`)
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/`([^`]+)`/g, '<code>$1</code>')
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')

    const lines = text.split('\n')
    let html = ''
    let listType = null
    let inList = false
    let quoteBuffer = []
    const closeList = () => {
        if (inList) {
            html += `</${listType}>`
            inList = false
            listType = null
        }
    }
    const flushQuote = () => {
        if (!quoteBuffer.length) return
        let depth = 0
        for (const item of quoteBuffer) {
            while (depth < item.depth) {
                html += '<blockquote>'
                depth++
            }
            while (depth > item.depth) {
                html += '</blockquote>'
                depth--
            }
            if (item.text) {
                html += `<p>${inline(item.text)}</p>`
            }
        }
        while (depth > 0) {
            html += '</blockquote>'
            depth--
        }
        quoteBuffer = []
    }
    const closeBlocks = () => {
        closeList()
        flushQuote()
    }

    for (const rawLine of lines) {
        const line = rawLine.trimEnd()
        if (!line.trim()) {
            closeBlocks()
            continue
        }
        const quote = line.match(/^(\s{0,3}>+)\s?(.*)$/)
        if (quote) {
            closeList()
            quoteBuffer.push({
                depth: quote[1].replace(/\s/g, '').length,
                text: quote[2],
            })
            continue
        }
        const heading = line.match(/^(#{1,3}) (.*)$/)
        if (heading) {
            closeBlocks()
            const level = heading[1].length
            html += `<h${level}>${inline(heading[2])}</h${level}>`
            continue
        }
        const unordered = line.match(/^\s*[-*] (.*)$/)
        if (unordered) {
            flushQuote()
            if (!inList || listType !== 'ul') {
                closeList()
                listType = 'ul'
                inList = true
                html += '<ul>'
            }
            html += `<li>${inline(unordered[1])}</li>`
            continue
        }
        const ordered = line.match(/^\s*\d+\. (.*)$/)
        if (ordered) {
            flushQuote()
            if (!inList || listType !== 'ol') {
                closeList()
                listType = 'ol'
                inList = true
                html += '<ol>'
            }
            html += `<li>${inline(ordered[1])}</li>`
            continue
        }
        closeBlocks()
        html += `<p>${inline(line)}</p>`
    }
    closeBlocks()
    return html
}

function formatFileSize(bytes) {
    if (bytes >= 1000 ** 3) {
        return `${(bytes / (1000 ** 3)).toFixed(2)} GB`
    }
    if (bytes >= 1000 ** 2) {
        return `${(bytes / (1000 ** 2)).toFixed(1)} MB`
    }
    if (bytes >= 1000) {
        return `${(bytes / 1000).toFixed(1)} KB`
    }
    return `${bytes} B`
}

;(function () {
    const content = document.getElementById('guideContent')

    const sampleSizeLabels = [...document.querySelectorAll('[data-sample-url]')]
    const updateSampleSizes = () => Promise.all(sampleSizeLabels.map((label) => {
        const latestUrl = new URL(label.dataset.sampleUrl, window.location.origin)
        latestUrl.searchParams.set('_', Date.now().toString())
        return fetch(latestUrl, {
            method: 'HEAD',
            cache: 'no-store',
        })
        .then((response) => {
            const length = Number(response.headers.get('content-length'))
            if (Number.isFinite(length) && length > 0) {
                label.textContent = formatFileSize(length)
            }
        })
        .catch(() => {
            label.textContent = 'ZIP 压缩包'
        })
    }))

    updateSampleSizes()
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            updateSampleSizes()
        }
    })

    fetch('/assets/guide.md')
        .then((response) => {
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`)
            }
            return response.text()
        })
        .then((text) => {
            content.innerHTML = renderMarkdown(text)
        })
        .catch(() => {
            content.innerHTML = '<div class="guide-error">说明文件加载失败，请下载一个测试病例后直接拖入上传区。</div>'
        })

    document.getElementById('guideBack').addEventListener('click', () => {
        window.location.href = 'index.html'
    })

    const themeButton = document.getElementById('guideTheme')
    const applyTheme = (theme) => {
        document.documentElement.setAttribute('data-theme', theme)
        themeButton.classList.toggle('dark', theme === 'dark')
    }
    themeButton.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark'
            ? 'light'
            : 'dark'
        localStorage.setItem('btir_theme', next)
        applyTheme(next)
    })
    applyTheme(localStorage.getItem('btir_theme') || 'light')
})()
