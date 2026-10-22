(function () {
    const API_BASE = window.btirEnv?.apiBase ?? ''
    const form = document.getElementById('changeForm')
    const submitBtn = document.getElementById('submitBtn')
    const messageBox = document.getElementById('message')

    const showMessage = (text, type) => {
        messageBox.textContent = text
        messageBox.className = `message ${type}`
        messageBox.style.display = 'block'
    }
    const hideMessage = () => {
        messageBox.style.display = 'none'
    }

    const themeButton = document.getElementById('themeToggle')
    const applyTheme = (theme) => {
        document.documentElement.setAttribute('data-theme', theme)
        themeButton.classList.toggle('dark', theme === 'dark')
        document.querySelector('.guide-icon-dark').style.display = theme === 'dark' ? '' : 'none'
        document.querySelector('.guide-icon-light').style.display = theme === 'dark' ? 'none' : ''
    }
    themeButton.addEventListener('click', () => {
        const next = document.documentElement.getAttribute('data-theme') === 'dark'
            ? 'light'
            : 'dark'
        localStorage.setItem('btir_theme', next)
        applyTheme(next)
    })
    applyTheme(localStorage.getItem('btir_theme') || 'light')

    // 未登录（无令牌）直接回登录页
    if (!localStorage.getItem('btir_token')) {
        window.location.href = './login.html'
        return
    }

    const authHeaders = () => {
        const token = localStorage.getItem('btir_token')
        return token ? { 'Authorization': `Bearer ${token}` } : {}
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault()
        hideMessage()

        const currentPassword = document.getElementById('currentPassword').value
        const newPassword = document.getElementById('newPassword').value
        const confirmPassword = document.getElementById('confirmPassword').value

        if (newPassword !== confirmPassword) {
            showMessage('两次输入的新密码不一致', 'error')
            return
        }
        if (newPassword.length < 6 || newPassword.length > 72) {
            showMessage('新密码长度应为 6 至 72 个字符', 'error')
            return
        }

        submitBtn.disabled = true
        submitBtn.textContent = '提交中...'
        try {
            const response = await fetch(`${API_BASE}/auth/change-password`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...authHeaders(),
                },
                body: JSON.stringify({
                    current_password: currentPassword,
                    new_password: newPassword,
                }),
            })
            let data = {}
            try {
                data = await response.json()
            } catch { /* 忽略非 JSON 响应 */ }
            if (!response.ok) {
                const detail = typeof data.detail === 'string'
                    ? data.detail
                    : (data.detail?.message || `修改失败：HTTP ${response.status}`)
                showMessage(detail, 'error')
                return
            }
            if (data.access_token) {
                localStorage.setItem('btir_token', data.access_token)
                localStorage.setItem('btir_user', JSON.stringify({
                    user_id: data.user_id,
                    username: data.username,
                }))
            }
            showMessage('密码修改成功，正在进入系统...', 'success')
            setTimeout(() => {
                window.location.href = './index.html'
            }, 600)
        } catch (err) {
            showMessage(`网络错误：${err.message || '请稍后重试'}`, 'error')
        } finally {
            submitBtn.disabled = false
            submitBtn.textContent = '确认修改'
        }
    })
})()
