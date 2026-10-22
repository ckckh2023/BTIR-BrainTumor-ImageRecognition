(function () {
    document.getElementById('aboutBack').addEventListener('click', () => {
        window.location.href = 'index.html'
    })

    const themeButton = document.getElementById('aboutTheme')
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

    const repositoryPicker = document.getElementById('repositoryPicker')
    const repositoryTriggers = document.querySelectorAll('.repository-picker-trigger')
    let repositoryPickerPreviousFocus = null

    const closeRepositoryPicker = () => {
        repositoryPicker.hidden = true
        document.body.classList.remove('repository-picker-open')
        repositoryPickerPreviousFocus?.focus()
    }

    const openRepositoryPicker = (event) => {
        repositoryPickerPreviousFocus = event.currentTarget
        repositoryPicker.hidden = false
        document.body.classList.add('repository-picker-open')
        repositoryPicker.querySelector('.repository-picker-close').focus()
    }

    repositoryTriggers.forEach((trigger) => {
        trigger.addEventListener('click', openRepositoryPicker)
    })
    repositoryPicker.querySelectorAll('[data-repository-picker-close]').forEach((button) => {
        button.addEventListener('click', closeRepositoryPicker)
    })
    document.addEventListener('keydown', (event) => {
        if (repositoryPicker.hidden) return
        if (event.key === 'Escape') {
            closeRepositoryPicker()
            return
        }
        if (event.key !== 'Tab') return
        const focusable = Array.from(repositoryPicker.querySelectorAll('a[href], button:not([disabled])'))
        const first = focusable[0]
        const last = focusable[focusable.length - 1]
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault()
            last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault()
            first.focus()
        }
    })
})()
