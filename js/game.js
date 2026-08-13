(function () {
    'use strict'

    const DIFFICULTIES = {
        easy: { name: '简单', rows: 8, columns: 8, mines: 10, maxLines: 1, firstDelay: 5400, spawnMin: 5000, spawnMax: 7000, moveEvery: 470, lineLength: 3, tumorDelay: 8200, tumorMin: 7600, tumorMax: 9400, tumorWarn: 1450, tumorLife: 2400, maxTumors: 1, splashRadius: 1, splashChance: .3 },
        normal: { name: '普通', rows: 12, columns: 12, mines: 24, maxLines: 2, firstDelay: 4000, spawnMin: 3200, spawnMax: 5000, moveEvery: 340, lineLength: 3, tumorDelay: 5800, tumorMin: 4800, tumorMax: 6400, tumorWarn: 1250, tumorLife: 3300, maxTumors: 2, splashRadius: 1, splashChance: .65 },
        hard: { name: '困难', rows: 16, columns: 16, mines: 48, maxLines: 3, firstDelay: 3000, spawnMin: 2000, spawnMax: 3500, moveEvery: 240, lineLength: 4, tumorDelay: 3900, tumorMin: 3100, tumorMax: 4500, tumorWarn: 1050, tumorLife: 4200, maxTumors: 3, splashRadius: 2, splashChance: .58 },
        extreme: { name: '极难', rows: 20, columns: 20, mines: 86, maxLines: 5, firstDelay: 1800, spawnMin: 1200, spawnMax: 2100, moveEvery: 145, lineLength: 5, tumorDelay: 2500, tumorMin: 1800, tumorMax: 2800, tumorWarn: 760, tumorLife: 5200, maxTumors: 4, splashRadius: 2, splashChance: .78 }
    }

    const TUMOR_SPLASH = {
        easy: { radius: 1, chance: .3 },
        normal: { radius: 1, chance: .65 },
        hard: { radius: 2, chance: .58 },
        extreme: { radius: 2, chance: .78 }
    }

    const board = document.getElementById('gameBoard')
    const boardStage = document.getElementById('boardStage')
    const threatPreviewLayer = document.getElementById('threatPreviewLayer')
    const brainActors = [...document.querySelectorAll('.brain-actor')]
    const difficultyList = document.getElementById('difficultyList')
    const restartButton = document.getElementById('restartButton')
    const mineCounter = document.getElementById('mineCounter')
    const timerValue = document.getElementById('timerValue')
    const progressValue = document.getElementById('progressValue')
    const threatValue = document.getElementById('threatValue')
    const threatBar = document.getElementById('threatBar')
    const status = document.getElementById('gameStatus')
    const footerMessage = document.getElementById('footerMessage')
    const resultModal = document.getElementById('resultModal')
    const resultCard = resultModal.querySelector('.result-card')
    const resultSymbol = document.getElementById('resultSymbol')
    const resultTitle = document.getElementById('resultTitle')
    const resultText = document.getElementById('resultText')
    const resultTime = document.getElementById('resultTime')
    const resultProgress = document.getElementById('resultProgress')
    const resultDifficulty = document.getElementById('resultDifficulty')
    const playAgain = document.getElementById('playAgain')
    const gameToast = document.getElementById('gameToast')
    const soundToggle = document.getElementById('soundToggle')

    let difficultyKey = 'easy'
    let config = DIFFICULTIES[difficultyKey]
    let mines = new Set()
    let revealed = new Set()
    let flagged = new Set()
    let firstScan = true
    let state = 'idle'
    let selected = 0
    let startedAt = null
    let finalSeconds = 0
    let timerHandle = null
    let threatHandle = null
    let nextSpawnAt = 0
    let nextMoveAt = 0
    let threatLines = []
    let tumorWarnings = new Map()
    let tumorCells = new Map()
    let tumorWaves = []
    let nextTumorAt = 0
    let inputMode = 'mouse'
    let muted = false
    let audioContext = null

    const indexOf = (row, column) => row * config.columns + column
    const positionOf = (index) => [Math.floor(index / config.columns), index % config.columns]

    function sampleMines(excluded = new Set()) {
        const candidates = []
        for (let index = 0; index < config.rows * config.columns; index += 1) if (!excluded.has(index)) candidates.push(index)
        for (let i = candidates.length - 1; i > 0; i -= 1) {
            const j = Math.floor(Math.random() * (i + 1)); [candidates[i], candidates[j]] = [candidates[j], candidates[i]]
        }
        return new Set(candidates.slice(0, config.mines))
    }

    function neighbors(index) {
        const [row, column] = positionOf(index)
        const cells = []
        for (let nextRow = Math.max(0, row - 1); nextRow <= Math.min(config.rows - 1, row + 1); nextRow += 1) {
            for (let nextColumn = Math.max(0, column - 1); nextColumn <= Math.min(config.columns - 1, column + 1); nextColumn += 1) {
                const next = indexOf(nextRow, nextColumn)
                if (next !== index) cells.push(next)
            }
        }
        return cells
    }

    function adjacentCount(index) { return neighbors(index).filter((cell) => mines.has(cell)).length }

    function createBoard() {
        board.innerHTML = ''
        board.style.setProperty('--board-size', config.columns)
        const cellSize = config.columns === 8 ? 48 : config.columns === 12 ? 37 : config.columns === 16 ? 29 : 34
        board.style.setProperty('--cell-size', `${cellSize}px`)
        for (let index = 0; index < config.rows * config.columns; index += 1) {
            const cell = document.createElement('button')
            const [row, column] = positionOf(index)
            cell.type = 'button'
            cell.className = 'game-cell'
            cell.dataset.index = String(index)
            cell.setAttribute('role', 'gridcell')
            cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，未扫描`)
            cell.tabIndex = index === selected ? 0 : -1
            board.appendChild(cell)
        }
        render()
    }

    function resetGame() {
        window.clearInterval(timerHandle)
        window.clearInterval(threatHandle)
        config = DIFFICULTIES[difficultyKey]
        Object.assign(config, TUMOR_SPLASH[difficultyKey])
        mines = sampleMines()
        revealed = new Set()
        flagged = new Set()
        firstScan = true
        state = 'idle'
        selected = 0
        startedAt = null
        finalSeconds = 0
        threatLines = []
        tumorWarnings = new Map()
        tumorCells = new Map()
        tumorWaves = []
        nextTumorAt = 0
        boardStage.querySelectorAll('.tumor-projectile').forEach((projectile) => projectile.remove())
        inputMode = 'mouse'
        nextSpawnAt = 0
        nextMoveAt = 0
        resultModal.hidden = true
        status.textContent = '等待首次扫描'
        status.className = 'game-status idle'
        footerMessage.textContent = '选择任意区域开始任务'
        createBoard()
        updateHud()
    }

    function beginIfNeeded() {
        if (state !== 'idle') return
        state = 'running'
        startedAt = performance.now()
        nextSpawnAt = startedAt + config.firstDelay
        nextMoveAt = startedAt + config.moveEvery
        nextTumorAt = startedAt + config.tumorDelay
        status.textContent = '扫描进行中'
        status.className = 'game-status running'
        footerMessage.textContent = '红色扫描线即将进入区域'
        timerHandle = window.setInterval(updateHud, 250)
        threatHandle = window.setInterval(advanceThreats, 80)
    }

    function protectOpening(index) {
        const protectedCells = new Set([index, ...neighbors(index)])
        const hasCollision = [...protectedCells].some((cell) => mines.has(cell))
        if (hasCollision) mines = sampleMines(protectedCells)
    }

    function floodReveal(start) {
        const pending = [start]
        while (pending.length) {
            const index = pending.shift()
            if (revealed.has(index) || flagged.has(index) || mines.has(index)) continue
            revealed.add(index)
            if (adjacentCount(index) === 0) pending.push(...neighbors(index))
        }
    }

    function reveal(index) {
        if (state === 'won' || state === 'lost' || flagged.has(index)) return
        if (tumorCells.has(index)) return toast('肿瘤干扰中，请等待该区域恢复')
        beginIfNeeded()
        if (firstScan) { protectOpening(index); firstScan = false }
        if (revealed.has(index)) {
            const nearby = neighbors(index)
            if (adjacentCount(index) > 0 && nearby.filter((cell) => flagged.has(cell)).length === adjacentCount(index)) {
                for (const cell of nearby) {
                    if (flagged.has(cell) || revealed.has(cell)) continue
                    if (mines.has(cell)) return lose('扫描标记有误，触发了异常信号')
                    floodReveal(cell)
                }
            }
        } else if (mines.has(index)) {
            revealed.add(index)
            render()
            return lose('扫描到异常信号，任务失败')
        } else {
            floodReveal(index)
            tone(610, .045)
        }
        if (revealed.size === config.rows * config.columns - config.mines) return win()
        render(); updateHud()
    }

    function toggleFlag(index) {
        if (state === 'won' || state === 'lost' || revealed.has(index)) return
        if (tumorCells.has(index)) return toast('肿瘤干扰中，暂不能标记')
        if (flagged.has(index)) flagged.delete(index)
        else if (flagged.size < config.mines) flagged.add(index)
        else return toast('标记数量已达到本局异常信号上限')
        tone(flagged.has(index) ? 390 : 280, .035)
        render(); updateHud()
    }

    function randomLine() {
        const horizontal = Math.random() < .5
        const blocked = horizontal ? positionOf(selected)[0] : positionOf(selected)[1]
        const fixedLimit = horizontal ? config.rows : config.columns
        const choices = Array.from({ length: fixedLimit }, (_, index) => index).filter((index) => index !== blocked)
        const step = Math.random() < .5 ? -1 : 1
        const limit = horizontal ? config.columns : config.rows
        return { horizontal, fixed: choices[Math.floor(Math.random() * choices.length)], step, offset: step > 0 ? -config.lineLength - 2 : limit + 2 }
    }

    function lineCells(line) {
        const cells = []
        const limit = line.horizontal ? config.columns : config.rows
        for (let moving = line.offset; moving < line.offset + config.lineLength; moving += 1) {
            if (moving < 0 || moving >= limit) continue
            cells.push(line.horizontal ? indexOf(line.fixed, moving) : indexOf(moving, line.fixed))
        }
        return cells
    }

    function advanceThreats() {
        if (state !== 'running') return
        const now = performance.now()
        if (now >= nextSpawnAt && threatLines.length < config.maxLines) {
            threatLines.push(randomLine())
            if (['hard', 'extreme'].includes(difficultyKey) && Math.random() < (difficultyKey === 'extreme' ? .8 : .45) && threatLines.length < config.maxLines) threatLines.push(randomLine())
            nextSpawnAt = now + config.spawnMin + Math.random() * (config.spawnMax - config.spawnMin)
            tone(175, .09)
        }
        if (now >= nextMoveAt) {
            threatLines.forEach((line) => { line.offset += line.step })
            const horizontalLimit = config.columns
            const verticalLimit = config.rows
            threatLines = threatLines.filter((line) => line.step > 0 ? line.offset < (line.horizontal ? horizontalLimit : verticalLimit) : line.offset + config.lineLength > 0)
            nextMoveAt = now + config.moveEvery
        }
        const tumorsChanged = updateTumors(now)
        const activeCells = new Set(threatLines.flatMap(lineCells))
        if (activeCells.has(selected)) return lose('红色扫描线已覆盖当前扫描位置，任务失败')
        if (tumorsChanged) render()
        else renderThreats(activeCells)
        updateThreatMeter()
    }

    function tumorSlots() {
        const fractions = [[.2,.2],[.5,.2],[.8,.2],[.2,.5],[.8,.5],[.2,.8],[.5,.8],[.8,.8],[.5,.5]]
        return fractions.map(([row, column]) => indexOf(Math.round((config.rows - 1) * row), Math.round((config.columns - 1) * column)))
    }

    function tumorBlastCells(center) {
        const { radius, chance: baseChance } = TUMOR_SPLASH[difficultyKey]
        const [centerRow, centerColumn] = positionOf(center)
        const cells = [{ index: center, center: true }]
        for (let row = centerRow - radius; row <= centerRow + radius; row += 1) {
            for (let column = centerColumn - radius; column <= centerColumn + radius; column += 1) {
                if (row < 0 || row >= config.rows || column < 0 || column >= config.columns) continue
                const index = indexOf(row, column)
                if (index === center || tumorWarnings.has(index) || tumorCells.has(index) || revealed.has(index) || flagged.has(index) || mines.has(index)) continue
                const distance = Math.max(Math.abs(row - centerRow), Math.abs(column - centerColumn))
                const chance = Math.max(.16, baseChance - (distance - 1) * .18)
                if (Math.random() < chance) cells.push({ index, center: false })
            }
        }
        return cells
    }

    function updateTumors(now) {
        let changed = false
        for (const [cell, warning] of tumorWarnings) {
            if (now < warning.landsAt) continue
            tumorWarnings.delete(cell)
            tumorCells.set(cell, now + config.tumorLife)
            footerMessage.textContent = '肿瘤已落入区域，暂时避开红色格子'
            tone(190, .14)
            changed = true
        }
        for (const [cell, expiresAt] of tumorCells) {
            if (now >= expiresAt) {
                tumorCells.delete(cell)
                changed = true
            }
        }
        tumorWaves = tumorWaves.filter((wave) => now < wave.expiresAt)
        if (now < nextTumorAt || tumorWaves.length >= config.maxTumors) return changed
        const candidates = tumorSlots().filter((cell) => !tumorWarnings.has(cell) && !tumorCells.has(cell) && !revealed.has(cell) && !flagged.has(cell) && !mines.has(cell))
        if (candidates.length) {
            const throws = Math.min(2, candidates.length, config.maxTumors - tumorWaves.length)
            const selectedTargets = candidates.sort(() => Math.random() - .5).slice(0, throws)
            selectedTargets.forEach((cell, actorIndex) => {
                tumorBlastCells(cell).forEach((target) => tumorWarnings.set(target.index, { landsAt: now + config.tumorWarn, center: target.center }))
                tumorWaves.push({ expiresAt: now + config.tumorWarn + config.tumorLife })
                throwTumor(cell, actorIndex)
            })
            footerMessage.textContent = '肿瘤正在锁定目标，圆环收缩后生效'
            tone(230, .12)
            changed = true
        }
        nextTumorAt = now + config.tumorMin + Math.random() * (config.tumorMax - config.tumorMin)
        return changed
    }

    function throwTumor(cell, actorIndex = null) {
        const target = board.children[cell]
        if (!target || !brainActors.length) return
        const stageRect = boardStage.getBoundingClientRect()
        const targetRect = target.getBoundingClientRect()
        const targetX = targetRect.left - stageRect.left + targetRect.width / 2
        const targetY = targetRect.top - stageRect.top + targetRect.height / 2
        const actor = actorIndex === null ? (targetX < stageRect.width / 2 ? brainActors[0] : brainActors[brainActors.length - 1]) : brainActors[actorIndex % brainActors.length]
        const actorRect = actor.getBoundingClientRect()
        const sourceX = actorRect.left - stageRect.left + actorRect.width / 2
        const sourceY = actorRect.top - stageRect.top + actorRect.height / 2
        const projectile = document.createElement('i')
        projectile.className = 'tumor-projectile'
        projectile.style.setProperty('--tumor-flight', `${config.tumorWarn}ms`)
        projectile.style.left = `${sourceX}px`
        projectile.style.top = `${sourceY}px`
        boardStage.appendChild(projectile)
        actor.classList.remove('throwing')
        void actor.offsetWidth
        actor.classList.add('throwing')
        window.setTimeout(() => actor.classList.remove('throwing'), 720)
        window.requestAnimationFrame(() => {
            projectile.style.left = `${targetX}px`
            projectile.style.top = `${targetY}px`
            projectile.style.transform = 'translate(-50%, -50%) scale(.25)'
            projectile.style.opacity = '0'
        })
        window.setTimeout(() => projectile.remove(), config.tumorWarn + 80)
    }

    function renderThreats(activeCells = new Set(threatLines.flatMap(lineCells))) {
        board.querySelectorAll('.game-cell').forEach((cell) => {
            const index = Number(cell.dataset.index)
            cell.classList.remove('threat', 'horizontal', 'vertical')
            const line = threatLines.find((candidate) => lineCells(candidate).includes(index))
            if (activeCells.has(index) && line) cell.classList.add('threat', line.horizontal ? 'horizontal' : 'vertical')
        })
        renderThreatPreviews()
    }

    function renderThreatPreviews() {
        threatPreviewLayer.replaceChildren()
        const stageRect = boardStage.getBoundingClientRect()
        const limit = (line) => line.horizontal ? config.columns : config.rows
        threatLines.forEach((line) => {
            const size = limit(line)
            const outside = line.step > 0 ? line.offset + config.lineLength <= 0 : line.offset >= size
            if (!outside) return
            const anchor = board.children[line.horizontal
                ? indexOf(line.fixed, line.step > 0 ? 0 : config.columns - 1)
                : indexOf(line.step > 0 ? 0 : config.rows - 1, line.fixed)]
            if (!anchor) return
            const rect = anchor.getBoundingClientRect()
            const preview = document.createElement('i')
            preview.className = 'threat-preview'
            preview.textContent = '!'
            if (line.horizontal) {
                preview.style.top = `${rect.top - stageRect.top + rect.height / 2}px`
                preview.style.left = `${line.step > 0 ? rect.left - stageRect.left - 36 : rect.right - stageRect.left + 20}px`
            } else {
                preview.style.left = `${rect.left - stageRect.left + rect.width / 2}px`
                preview.style.top = `${line.step > 0 ? rect.top - stageRect.top - 36 : rect.bottom - stageRect.top + 20}px`
            }
            threatPreviewLayer.appendChild(preview)
        })
    }

    function render() {
        board.querySelectorAll('.game-cell').forEach((cell) => {
            const index = Number(cell.dataset.index)
            const [row, column] = positionOf(index)
            cell.className = 'game-cell'
            cell.textContent = ''
            cell.tabIndex = index === selected ? 0 : -1
            if (index === selected) cell.classList.add('selected')
            const tumorWarning = tumorWarnings.get(index)
            if (tumorWarning) {
                cell.classList.add(tumorWarning.center ? 'tumor-target' : 'tumor-splash-target')
                cell.style.setProperty('--tumor-lock-duration', `${config.tumorWarn}ms`)
            }
            if (tumorCells.has(index)) {
                cell.classList.add('tumor-blocked')
                cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，肿瘤干扰中`)
            } else if (flagged.has(index)) {
                cell.classList.add('flagged')
                cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，已标记异常`)
            } else if (revealed.has(index)) {
                if (mines.has(index)) {
                    cell.classList.add('mine')
                    cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，异常信号`)
                } else {
                    const count = adjacentCount(index)
                    cell.classList.add('revealed', `n${count}`)
                    cell.textContent = count ? String(count) : ''
                    cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，已扫描，周围 ${count} 个异常信号`)
                }
            } else cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，未扫描`)
            if (tumorWarning) cell.setAttribute('aria-label', `第 ${row + 1} 行，第 ${column + 1} 列，肿瘤${tumorWarning.center ? '即将落点' : '溅射预警'}`)
        })
        if (state === 'lost') {
            mines.forEach((index) => {
                const cell = board.children[index]
                if (!flagged.has(index)) cell.classList.add('mine')
            })
        }
        renderThreats()
    }

    function elapsedSeconds() { return startedAt ? (state === 'running' ? (performance.now() - startedAt) / 1000 : finalSeconds) : 0 }
    function formatTime(seconds) { const total = Math.floor(seconds); return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}` }
    function progress() { return Math.round(revealed.size / (config.rows * config.columns - config.mines) * 100) }
    function updateHud() { mineCounter.textContent = String(Math.max(0, config.mines - flagged.size)); timerValue.textContent = formatTime(elapsedSeconds()); progressValue.textContent = `${Math.min(100, progress())}%`; updateThreatMeter() }
    function updateThreatMeter() {
        const ratio = config.maxLines ? threatLines.length / config.maxLines : 0
        const label = ratio >= .8 ? '高' : ratio >= .4 ? '中' : '低'
        threatValue.textContent = label
        threatBar.style.width = `${22 + ratio * 78}%`
        threatBar.style.background = label === '高' ? 'var(--btir-danger)' : label === '中' ? 'var(--btir-warning)' : 'var(--btir-success)'
    }

    function finish(won, message) {
        state = won ? 'won' : 'lost'
        finalSeconds = startedAt ? (performance.now() - startedAt) / 1000 : 0
        window.clearInterval(timerHandle); window.clearInterval(threatHandle)
        threatLines = []
        status.textContent = won ? '任务完成' : '任务中止'
        status.className = `game-status ${state}`
        footerMessage.textContent = message
        render(); updateHud()
        window.setTimeout(() => showResult(won, message), 450)
        tone(won ? 760 : 115, won ? .22 : .32)
    }
    function win() { finish(true, '安全区域已全部确认，异常信号定位完成') }
    function lose(message) { if (state !== 'won' && state !== 'lost') finish(false, message) }
    function showResult(won, message) {
        resultCard.classList.toggle('failed', !won)
        resultSymbol.textContent = won ? '✓' : '×'
        resultTitle.textContent = won ? '扫描任务完成' : '扫描任务失败'
        resultText.textContent = won ? '你成功完成了本次影像排查。所有安全区域均已确认。' : message
        resultTime.textContent = formatTime(finalSeconds)
        resultProgress.textContent = `${Math.min(100, progress())}%`
        resultDifficulty.textContent = config.name
        resultModal.hidden = false
        playAgain.focus()
    }

    function moveSelection(deltaRow, deltaColumn) {
        if (state === 'won' || state === 'lost') return
        inputMode = 'keyboard'
        const [row, column] = positionOf(selected)
        const nextRow = Math.max(0, Math.min(config.rows - 1, row + deltaRow))
        const nextColumn = Math.max(0, Math.min(config.columns - 1, column + deltaColumn))
        selected = indexOf(nextRow, nextColumn)
        render()
        board.children[selected].focus({ preventScroll: true })
    }

    function toast(message) { gameToast.textContent = message; gameToast.classList.add('show'); window.clearTimeout(toast.handle); toast.handle = window.setTimeout(() => gameToast.classList.remove('show'), 1800) }
    function tone(frequency, duration) {
        if (muted) return
        try {
            audioContext = audioContext || new (window.AudioContext || window.webkitAudioContext)()
            const oscillator = audioContext.createOscillator(); const gain = audioContext.createGain()
            oscillator.frequency.value = frequency; oscillator.type = 'sine'; gain.gain.value = .035
            oscillator.connect(gain); gain.connect(audioContext.destination); oscillator.start(); gain.gain.exponentialRampToValueAtTime(.0001, audioContext.currentTime + duration); oscillator.stop(audioContext.currentTime + duration)
        } catch (e) { /* 音频不可用 */ }
    }

    board.addEventListener('click', (event) => { const cell = event.target.closest('.game-cell'); if (!cell) return; inputMode = 'mouse'; selected = Number(cell.dataset.index); reveal(selected) })
    board.addEventListener('contextmenu', (event) => { const cell = event.target.closest('.game-cell'); if (!cell) return; event.preventDefault(); inputMode = 'mouse'; selected = Number(cell.dataset.index); toggleFlag(selected) })
    board.addEventListener('pointermove', (event) => {
        const cell = event.target.closest('.game-cell')
        if (!cell || inputMode !== 'mouse' || state === 'won' || state === 'lost') return
        const next = Number(cell.dataset.index)
        if (next === selected) return
        selected = next
        render()
    })
    document.addEventListener('keydown', (event) => {
        if (!resultModal.hidden) { if (event.key === 'Escape') resultModal.hidden = true; return }
        if (event.target.closest('a, button:not(.game-cell)')) return
        const key = event.key.toLowerCase()
        const moves = { arrowup: [-1, 0], w: [-1, 0], arrowdown: [1, 0], s: [1, 0], arrowleft: [0, -1], a: [0, -1], arrowright: [0, 1], d: [0, 1] }
        if (moves[key]) { event.preventDefault(); moveSelection(...moves[key]) }
        else if (key === ' ' || key === 'enter' || key === 'j') { event.preventDefault(); reveal(selected) }
        else if (key === 'f' || key === 'k') { event.preventDefault(); toggleFlag(selected) }
    })
    difficultyList.addEventListener('click', (event) => {
        const button = event.target.closest('[data-difficulty]')
        if (!button) return
        difficultyKey = button.dataset.difficulty
        difficultyList.querySelectorAll('button').forEach((item) => item.classList.toggle('active', item === button))
        document.body.classList.toggle('extreme-mode', difficultyKey === 'extreme')
        if (difficultyKey === 'extreme' && !document.fullscreenElement) document.documentElement.requestFullscreen?.().catch(() => {})
        resetGame()
    })
    restartButton.addEventListener('click', resetGame)
    playAgain.addEventListener('click', resetGame)
    resultModal.addEventListener('click', (event) => { if (event.target === resultModal) resultModal.hidden = true })
    soundToggle.addEventListener('click', () => { muted = !muted; soundToggle.classList.toggle('muted', muted); soundToggle.setAttribute('aria-label', muted ? '开启游戏音效' : '关闭游戏音效'); toast(muted ? '音效已关闭' : '音效已开启') })
    const gameTheme = document.getElementById('gameTheme')
    gameTheme.setAttribute('aria-pressed', String(document.documentElement.getAttribute('data-theme') === 'dark'))
    gameTheme.addEventListener('click', () => { const theme = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark'; document.documentElement.setAttribute('data-theme', theme); gameTheme.setAttribute('aria-pressed', String(theme === 'dark')); try { localStorage.setItem('btir_theme', theme) } catch (e) { /* 忽略 */ } })

    resetGame()
})()
