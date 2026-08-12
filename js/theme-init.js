(function () {
    'use strict'

    document.documentElement.classList.add('js')

    let theme = 'light'
    try {
        theme = localStorage.getItem('btir_theme') || 'light'
    } catch (error) {
        theme = 'light'
    }
    document.documentElement.setAttribute('data-theme', theme)
})()
