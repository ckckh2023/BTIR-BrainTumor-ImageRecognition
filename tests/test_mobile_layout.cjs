/* Run with Node + Playwright. Set BTIR_BROWSER_EXECUTABLE for a system Chrome.
   All APIs and volume rendering are local fixtures; no models or network needed. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const frontend = process.env.BTIR_FRONTEND_ROOT || path.join(root, 'frontend');
const baseline = process.env.BTIR_MOBILE_BASELINE === '1';
const origin = 'http://btir-mobile.test';
const modalities = ['flair', 't1ce', 't1', 't2'];
const files = Object.fromEntries(modalities.map(key => [key, `${key}.nii.gz`]));
const task = {
    task_id: 'mobile-case', name: '手机适配检查病例', status: 'succeeded', analysis_mode: '3d',
    created_at: '2026-10-17T00:00:00Z', input: { files },
    frontend_result: {
        input_files: files, result_files: { frontend: 'frontend_result.json', mask: 'prediction.nii.gz' },
        classification: { class: 'yes', confidence: 0.91 },
        segmentation: { mask_file: 'prediction.nii.gz', regions: { 1: { volume_mm3: 42, ratio: 0.01 } } },
    },
};
async function installFixtures(context) {
    await context.addInitScript(() => {
        if (!location.pathname.startsWith('/login/')) localStorage.setItem('btir_token', 'test-only');
    });
    await context.route('**/*', route => {
        const url = new URL(route.request().url());
        const p = url.pathname;
        const json = body => route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) });
        if (url.origin !== origin) return route.abort();
        if (p === '/auth/me') return json({ user_id: 'test', username: 'mobile_user' });
        if (p === '/frontend-config') return json({});
        if (p.endsWith('/follow-up')) return json({ items: [], baseline: null });
        if (p.endsWith('/runs')) return json({ items: [], total: 0 });
        if (p.includes('/files/')) {
            if (p.endsWith('.json')) return json(task.frontend_result);
            return route.fulfill({ body: Buffer.from('test-volume') });
        }
        if (p === '/tasks') return json({ items: [task], total: 1 });
        if (p === '/tasks/3d/archive') return json({ task_id: task.task_id });
        if (p.endsWith('/run-async')) return json({ status: 'queued' });
        if (p.startsWith('/tasks/')) return json(task);
        if (p.endsWith('/volume_viewer.js')) return route.fulfill({
            contentType: 'text/javascript',
            body: `window.BtirVolumeViewer=class{constructor(c){this.c=c}async load(){this.c.dataset.loaded='true'}setViewMode(){}setMaskOpacity(){}drawScene(){}cleanup(){}}`,
        });
        const file = p.startsWith('/assets/')
            ? path.join(root, p)
            : path.join(frontend, p.replace(/^\/(web|login)\//, '') || 'index.html');
        if (!fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
        return route.fulfill({ path: file });
    });
}
async function measurements(page) {
    return page.evaluate(() => {
        const rect = selector => {
            const el = document.querySelector(selector);
            if (!el || !el.getClientRects().length) return null;
            const r = el.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
        };
        return {
            overflow: document.documentElement.scrollWidth - innerWidth,
            brand: rect('.app-title-group'), title: rect('.app-title-text h1'),
            nav: rect('.app-main-nav'), data: rect('.case-data-column'),
            viewer: rect('.case-viewer-column'), canvas: rect('canvas'),
            content: rect('.right-content'),
        };
    });
}
function fits(r, width, label) {
    assert(r && r.width > 0 && r.x >= -1 && r.right <= width + 1, `${label} clipped at ${width}px: ${JSON.stringify(r)}`);
}
(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.BTIR_BROWSER_EXECUTABLE || undefined });
    const rows = [];
    try {
        for (const theme of ['light', 'dark']) {
            for (const [width, height] of [[320,844],[375,844],[390,844],[480,844],[600,844],[760,844],[768,844],[900,844],[1024,844],[1440,844],[844,390]]) {
                const context = await browser.newContext({ viewport: { width, height }, hasTouch: true, reducedMotion: 'reduce' });
                await installFixtures(context);
                await context.addInitScript(t => localStorage.setItem('btir_theme', t), theme);
                const page = await context.newPage();
                const errors = [];
                page.on('pageerror', e => errors.push(e.message));
                for (const [view, query] of [['upload',''], ['result','?task=mobile-case'], ['tasks','?view=tasks']]) {
                    // Isolate the requested view from persisted workspace history.
                    await page.goto(origin + '/web/' + query);
                    await page.locator('[data-testid=logout]').waitFor();
                    if (view === 'result') await page.locator('canvas[data-loaded=true]').waitFor();
                    if (view === 'tasks') await page.locator('.task-card').waitFor();
                    const m = await measurements(page);
                    rows.push({ width, height, theme, view, ...m });
                    if (process.env.BTIR_MOBILE_SCREENSHOTS && width === 390) {
                        fs.mkdirSync(process.env.BTIR_MOBILE_SCREENSHOTS, { recursive: true });
                        await page.screenshot({ path: path.join(process.env.BTIR_MOBILE_SCREENSHOTS, `${theme}-${view}.png`), fullPage: true });
                    }
                    if (!baseline) {
                        assert(m.overflow <= 1, `${view} overflow at ${width}`);
                        fits(m.brand, width, 'brand');
                        assert(m.title.height <= 28, `title wraps at ${width}`);
                        if (view === 'result') {
                            fits(m.viewer, width, 'viewer');
                            fits(m.data, width, 'results');
                            assert(m.canvas.height > 60, 'canvas has no usable height');
                            if (width <= 1000) assert(m.data.bottom <= m.viewer.y + 1, 'result and viewer must stack');
                        }
                        if (width <= 760) {
                            assert(Math.abs(m.nav.bottom - height) <= 1, 'navigation must stay within reach');
                            const small = await page.locator('.app-main-nav button, .app-user-area button, .app-user-area a, .volume-source-menu button').evaluateAll(els => els.filter(el => {
                                const r = el.getBoundingClientRect();
                                return r.width > 0 && r.height > 0 && (r.width < 43 || r.height < 43);
                            }).map(el => el.textContent.trim() || el.getAttribute('aria-label')));
                            assert.deepEqual(small, [], 'primary touch targets must be at least 44px');
                            if (view === 'upload') {
                                await page.getByRole('button', { name: '手动上传四个 NIfTI 文件', exact: true }).click();
                                assert.equal(await page.locator('.volume-modal-files-panel .volume-input-row').count(), 4);
                            }
                            if (view === 'result') {
                                await page.getByRole('link', { name: '查看三维影像', exact: true }).click();
                                await page.getByRole('button', { name: '放大查看', exact: true }).click();
                                await page.locator('.volume-viewer-expanded').waitFor();
                                await page.waitForFunction(() => {
                                    const r = document.querySelector('.volume-viewer-expanded')?.getBoundingClientRect();
                                    return r && Math.abs(r.height - innerHeight) <= 1;
                                });
                                const expanded = await page.locator('.volume-viewer-expanded').boundingBox();
                                assert(Math.abs(expanded.y) <= 1 && Math.abs(expanded.height - height) <= 1, `expanded ${width}: ${JSON.stringify(expanded)}`);
                                await page.getByRole('button', { name: '缩小查看', exact: true }).click();
                                // A bottom navigation tap from deep in results must open the next view at its top.
                                await page.getByTestId('task-manager-tab').click();
                                await page.waitForFunction(() => scrollY === 0);
                            }
                        }
                    }
                    await page.evaluate(() => { localStorage.removeItem('btir_workspace'); sessionStorage.removeItem('btir_workspace'); });
                }
                if (!baseline) {
                    await page.evaluate(() => localStorage.removeItem('btir_token'));
                    await page.goto(origin + '/login/login.html');
                    await page.getByTestId('login-username').waitFor();
                    const font = await page.getByTestId('login-username').evaluate(el => parseFloat(getComputedStyle(el).fontSize));
                    if (width <= 560) assert(font >= 16, 'mobile text fields should avoid focus zoom');
                    await page.getByTestId('login-username').fill('mobile_user');
                    await page.getByTestId('login-password').fill('test-password');
                    assert((await measurements(page)).overflow <= 1, 'login overflow');
                    assert.deepEqual(errors, []);
                }
                await context.close();
            }
        }
        if (!baseline) {
            const context = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true, reducedMotion: 'reduce' });
            await installFixtures(context);
            const page = await context.newPage();
            await page.goto(origin + '/web/');
            const chooser = page.waitForEvent('filechooser');
            await page.getByRole('button', { name: '上传 ZIP 压缩包', exact: true }).click();
            await (await chooser).setFiles({ name: 'case.zip', mimeType: 'application/zip', buffer: Buffer.from('fixture') });
            assert(await page.getByTestId('start-analysis').isEnabled());
            await page.getByTestId('start-analysis').click();
            await page.locator('canvas[data-loaded=true]').waitFor();
            await page.getByRole('button', { name: '重新上传病例', exact: true }).click();
            await page.getByTestId('volume-drop-zone').waitFor();
            assert(await page.getByTestId('start-analysis').isDisabled());
            await context.close();
        }
        if (process.env.BTIR_MOBILE_METRICS) fs.writeFileSync(process.env.BTIR_MOBILE_METRICS, JSON.stringify(rows, null, 2));
        console.log(`PASS: ${rows.length} layout scenarios; ${baseline ? 'baseline measurements only' : 'touch targets, upload choices, result jumps, full screen, bottom navigation, login and browser errors'}.`);
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
