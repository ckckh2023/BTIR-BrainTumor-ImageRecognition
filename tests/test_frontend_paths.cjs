const assert = require('node:assert/strict')
const { readFileSync } = require('node:fs')
const path = require('node:path')
const { test } = require('node:test')
const vm = require('node:vm')

const source = readFileSync(path.join(__dirname, '../frontend/scripts/volume_viewer.js'), 'utf8')

test('查看器移动后仍从同一挂载目录加载 NiiVue，且保留延迟加载', async () => {
    for (const mount of ['web', 'login']) {
        const requested = []
        class Canvas {}
        const browser = { WebGL2RenderingContext: class {} }
        const context = {
            URL, window: browser, HTMLCanvasElement: Canvas,
            document: {
                currentScript: { src: `http://localhost/${mount}/scripts/volume_viewer.js` },
                createElement: () => ({ dataset: {} }),
                head: { appendChild(script) { requested.push(script.src); script.onerror() } },
            },
        }
        vm.runInNewContext(source, context)
        const viewer = new browser.BtirVolumeViewer(new Canvas())
        assert.equal(requested.length, 0)
        await assert.rejects(viewer.initialize(), /NiiVue 组件加载失败/)
        assert.deepEqual(requested, [`http://localhost/${mount}/vendor/niivue.umd.js`])
    }
})
