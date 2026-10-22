(function () {
    try {
        const url = new URL(window.location.href)
        if (
            url.searchParams.get('task')
            || url.searchParams.get('view')
            || sessionStorage.getItem('btir_workspace')
            || localStorage.getItem('btir_workspace')
        ) {
            document.documentElement.classList.add('btir-workspace-restoring')
        }
    } catch { /* 存储不可用时保留默认页面 */ }
})()
