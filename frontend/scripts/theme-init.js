(function () {
    let theme = 'light'
    try {
        theme = localStorage.getItem('btir_theme') === 'dark' ? 'dark' : 'light'
    } catch { /* 存储不可用时使用浅色主题 */ }
    document.documentElement.setAttribute('data-theme', theme)
})()
