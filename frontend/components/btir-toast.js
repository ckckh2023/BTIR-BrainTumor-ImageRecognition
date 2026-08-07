;(function (global) {
    'use strict'
    const Vue = global.Vue
    if (!Vue) return

    Vue.component('btir-toast', {
        data() {
            return {
                visible: false,
                type: 'success',
                message: '已复制到剪贴板',
                timer: null,
            }
        },
        mounted() {
            global.addEventListener('btir:toast', this.onToast)
        },
        beforeUnmount() {
            global.removeEventListener('btir:toast', this.onToast)
        },
        methods: {
            onToast(event) {
                const detail = (event && event.detail) || {}
                this.message = detail.message || '已复制到剪贴板'
                this.type = detail.type || 'success'
                this.visible = true
                clearTimeout(this.timer)
                this.timer = setTimeout(() => {
                    this.visible = false
                }, 2200)
            },
        },
        template: `
            <div class="app-toast" :class="[type, { show: visible }]">
                <span class="app-toast-icon" v-if="type === 'success'">✓</span>
                <span class="app-toast-icon" v-else-if="type === 'error'">✕</span>
                <span>{{ message }}</span>
            </div>
        `,
    })
})(window)
