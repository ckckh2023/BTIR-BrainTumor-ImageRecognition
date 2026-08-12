(function () {
    'use strict'

    const root = document.documentElement
    const themeToggle = document.getElementById('themeToggle')
    const mobileMenu = document.getElementById('mobileMenu')
    const siteNav = document.querySelector('.site-nav')
    const logo = document.getElementById('draggableLogo')
    const brandZone = document.getElementById('brandZone')
    const dragHint = document.getElementById('dragHint')

    themeToggle.addEventListener('click', () => {
        const theme = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'
        root.setAttribute('data-theme', theme)
        themeToggle.setAttribute('aria-pressed', String(theme === 'dark'))
        try { localStorage.setItem('btir_theme', theme) } catch (e) { /* 忽略 */ }
    })
    themeToggle.setAttribute('aria-pressed', String(root.getAttribute('data-theme') === 'dark'))

    mobileMenu.addEventListener('click', () => {
        const open = siteNav.classList.toggle('open')
        mobileMenu.setAttribute('aria-expanded', String(open))
    })
    siteNav.addEventListener('click', () => {
        siteNav.classList.remove('open')
        mobileMenu.setAttribute('aria-expanded', 'false')
    })
    document.addEventListener('click', (event) => {
        if (!siteNav.classList.contains('open')) return
        if (siteNav.contains(event.target) || mobileMenu.contains(event.target)) return
        siteNav.classList.remove('open')
        mobileMenu.setAttribute('aria-expanded', 'false')
    })
    document.addEventListener('keydown', (event) => {
        if (event.key !== 'Escape' || !siteNav.classList.contains('open')) return
        siteNav.classList.remove('open')
        mobileMenu.setAttribute('aria-expanded', 'false')
        mobileMenu.focus()
    })

    const revealItems = document.querySelectorAll('.reveal-item')
    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('visible')
                    observer.unobserve(entry.target)
                }
            })
        }, { threshold: 0.12 })
        revealItems.forEach((item) => observer.observe(item))
    } else {
        revealItems.forEach((item) => item.classList.add('visible'))
    }

    let activePointer = null
    let startPointer = { x: 0, y: 0 }
    let startOffset = { x: 0, y: 0 }
    let offset = { x: 0, y: 0 }
    let dragged = false

    function setLogoPosition(x, y) {
        const maxX = Math.max(72, Math.min(window.innerWidth - 78, 310))
        const maxY = Math.max(54, Math.min(window.innerHeight - 90, 210))
        offset.x = Math.max(-4, Math.min(maxX, x))
        offset.y = Math.max(-6, Math.min(maxY, y))
        logo.style.transform = `translate(${offset.x}px, ${offset.y}px)`
        const moved = Math.hypot(offset.x, offset.y) > 28
        brandZone.classList.toggle('logo-moved', moved)
        if (moved) {
            dragHint.classList.remove('show')
            try { localStorage.setItem('btir_easter_found', '1') } catch (e) { /* 忽略 */ }
        }
    }

    logo.addEventListener('pointerdown', (event) => {
        if (activePointer !== null) return
        activePointer = event.pointerId
        startPointer = { x: event.clientX, y: event.clientY }
        startOffset = { ...offset }
        dragged = false
        logo.classList.add('dragging')
        logo.setPointerCapture(event.pointerId)
        event.preventDefault()
    })
    logo.addEventListener('pointermove', (event) => {
        if (event.pointerId !== activePointer) return
        const dx = event.clientX - startPointer.x
        const dy = event.clientY - startPointer.y
        if (Math.hypot(dx, dy) > 4) dragged = true
        setLogoPosition(startOffset.x + dx, startOffset.y + dy)
    })
    function finishDrag(event) {
        if (event.pointerId !== activePointer) return
        logo.classList.remove('dragging')
        try { logo.releasePointerCapture(event.pointerId) } catch (e) { /* 已释放 */ }
        activePointer = null
    }
    logo.addEventListener('pointerup', finishDrag)
    logo.addEventListener('pointercancel', finishDrag)
    logo.addEventListener('click', (event) => {
        if (dragged) { event.preventDefault(); return }
        if (brandZone.classList.contains('logo-moved')) setLogoPosition(0, 0)
    })
    logo.addEventListener('keydown', (event) => {
        const step = event.shiftKey ? 40 : 12
        const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }
        if (moves[event.key]) {
            event.preventDefault()
            setLogoPosition(offset.x + moves[event.key][0], offset.y + moves[event.key][1])
        } else if (event.key === 'Escape' || event.key === 'Home') {
            event.preventDefault()
            setLogoPosition(0, 0)
        }
    })
    window.addEventListener('resize', () => setLogoPosition(offset.x, offset.y))

    let discovered = false
    try { discovered = localStorage.getItem('btir_easter_found') === '1' } catch (e) { /* 忽略 */ }
    if (!discovered) {
        window.setTimeout(() => dragHint.classList.add('show'), 1800)
        window.setTimeout(() => dragHint.classList.remove('show'), 6200)
    }
})()
