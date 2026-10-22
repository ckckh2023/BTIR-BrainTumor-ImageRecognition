const { createApp } = Vue

createApp({
    data() {
        return {
            API_BASE: window.btirEnv?.apiBase ?? '',
            mode: 'login',
            username: '',
            password: '',
            loading: false,
            msg: '',
            msgType: 'error',
            theme: 'light',
        }
    },
    methods: {
        applyTheme() {
            document.documentElement.setAttribute('data-theme', this.theme)
        },
        toggleTheme() {
            this.theme = this.theme === 'dark' ? 'light' : 'dark'
            localStorage.setItem('btir_theme', this.theme)
            this.applyTheme()
        },
        switchMode(mode) {
            this.mode = mode
            this.msg = ''
            this.msgType = 'error'
        },
        credentialsValidationMessage() {
            if (!this.username) {
                return '请输入用户名'
            }
            const usernameLength = Array.from(this.username).length
            const usernameMinLength = /^[\x00-\x7F]+$/.test(this.username) ? 3 : 2
            if (usernameLength < usernameMinLength || usernameLength > 32) {
                return '用户名长度应为 2 至 32 个字符，纯英文或数字用户名至少 3 个字符'
            }
            if (!/^[\p{L}\p{M}\p{N}_-]+$/u.test(this.username)) {
                return '用户名仅支持各语言的字母、数字、下划线和连字符'
            }
            if (!this.password) {
                return '请输入密码'
            }
            if (this.password.length < 6 || this.password.length > 72) {
                return '密码长度应为 6 至 72 个字符'
            }
            if (new TextEncoder().encode(this.password).length > 72) {
                return '密码的 UTF-8 编码不能超过 72 字节'
            }
            return ''
        },
        async responseErrorMessage(response, fallback) {
            const data = await response.json().catch(() => ({}))
            if (typeof data.detail === 'string' && data.detail) {
                return data.detail
            }
            if (Array.isArray(data.detail) && typeof data.detail[0]?.msg === 'string') {
                return data.detail[0].msg.replace(/^Value error,\s*/, '')
            }
            return fallback
        },
        async submit() {
            this.msg = ''
            const validationMessage = this.credentialsValidationMessage()
            if (validationMessage) {
                this.msg = validationMessage
                this.msgType = 'error'
                return
            }
            this.loading = true

            try {
                if (this.mode === 'register') {
                    const res = await fetch(`${this.API_BASE}/auth/register`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            username: this.username,
                            password: this.password,
                        }),
                    })
                    if (!res.ok) {
                        throw new Error(await this.responseErrorMessage(res, `注册失败：HTTP ${res.status}`))
                    }
                    const data = await res.json()
                    this.onAuthSuccess(data)
                } else {
                    const res = await fetch(`${this.API_BASE}/auth/login`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            username: this.username,
                            password: this.password,
                        }),
                    })
                    if (!res.ok) {
                        throw new Error(await this.responseErrorMessage(res, `登录失败：HTTP ${res.status}`))
                    }
                    const data = await res.json()
                    this.onAuthSuccess(data)
                }
            } catch (err) {
                this.msg = err.message
                this.msgType = 'error'
            } finally {
                this.loading = false
            }
        },
        onAuthSuccess(data) {
            localStorage.setItem('btir_token', data.access_token)
            localStorage.setItem('btir_user', JSON.stringify({
                user_id: data.user_id,
                username: data.username,
            }))
            if (data.must_change_password) {
                window.location.href = './change-password.html'
                return
            }
            window.location.href = './index.html'
        },
    },
    async mounted() {
        const savedTheme = localStorage.getItem('btir_theme')
        this.theme = savedTheme || 'light'
        this.applyTheme()

        const token = localStorage.getItem('btir_token')
        if (!token) return
        try {
            const response = await fetch(`${this.API_BASE}/auth/me`, {
                headers: { 'Authorization': `Bearer ${token}` },
            })
            if (response.ok) {
                window.location.href = './index.html'
                return
            }
        } catch {
        }
        if (token) {
            localStorage.removeItem('btir_token')
            localStorage.removeItem('btir_user')
        }
    },
}).mount('#app')
