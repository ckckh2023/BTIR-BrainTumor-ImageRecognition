(function (root) {
    const phases = {
        idle: { start: 0, end: 0, duration: 0 },
        upload: { start: 0, end: 10, duration: 15_000 },
        queued: { start: 10, end: 10, duration: 0 },
        classification: { start: 10, end: 20, duration: 15_000 },
        segmentation: { start: 20, end: 90, duration: 110_000 },
        summary: { start: 90, end: 99, duration: 20_000 },
        complete: { start: 100, end: 100, duration: 0 },
    }

    class AnalysisProgress {
        constructor() {
            this.reset()
        }

        reset() {
            this.phase = 'idle'
            this.raw = 0
            this.phaseStartedAt = 0
            this.sampleAt = 0
            this.lastFrameAt = null
        }

        update(phase, raw, now) {
            if (!Object.hasOwn(phases, phase)) return
            const value = Math.min(100, Math.max(0, Number(raw) || 0))
            if (phase !== this.phase) {
                this.phase = phase
                this.phaseStartedAt = now
                this.sampleAt = now
            } else if (value > this.raw) {
                this.sampleAt = now
            }
            this.raw = Math.max(this.raw, value)
        }

        get ceiling() {
            return phases[this.phase].end
        }

        get mappedPercent() {
            const fraction = (start, span) => Math.min(1, Math.max(0, (this.raw - start) / span))
            switch (this.phase) {
                case 'upload': return fraction(0, 36) * 10
                case 'queued': return 10
                case 'classification': return 10 + fraction(36, 8) * 10
                case 'segmentation': return 20 + fraction(44, 54) * 70
                case 'summary': return 90
                case 'complete': return 100
                default: return 0
            }
        }

        target(now) {
            const phase = phases[this.phase]
            const elapsed = Math.max(0, now - this.phaseStartedAt)
            const mapped = this.mappedPercent
            // 参考预算结束时补间走完本阶段约 90%；更慢的任务逐渐放缓。
            const eased = phase.duration ? 1 - Math.exp(-Math.LN10 * elapsed / phase.duration) : 0
            if (this.phase === 'classification') {
                return Math.max(mapped, Math.min(19.75, phase.start + 10 * eased))
            }
            if (this.phase === 'summary') {
                return phase.start + 9 * eased
            }
            if (this.phase === 'segmentation') {
                const sampleElapsed = Math.max(0, now - this.sampleAt)
                const leadDuration = phase.duration / (phase.end - phase.start) * 2
                const lead = 2 * (1 - Math.exp(-sampleElapsed / leadDuration))
                return Math.max(mapped, Math.min(89.75, mapped + lead))
            }
            return mapped
        }

        advance(current, now) {
            const elapsed = this.lastFrameAt === null ? 0 : Math.max(0, Math.min(100, now - this.lastFrameAt))
            this.lastFrameAt = now
            const target = this.target(now)
            if (target <= current) return current
            const next = this.phase === 'complete'
                ? Math.min(target, current + elapsed * 0.12)
                : current + (target - current) * (1 - Math.exp(-elapsed / 250))
            return target - next < 0.000001 ? target : next
        }
    }

    root.BtirAnalysisProgress = AnalysisProgress
})(globalThis)
