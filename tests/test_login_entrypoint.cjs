const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const test = require('node:test')
const vm = require('node:vm')

const html = fs.readFileSync(path.join(__dirname, '../frontend/login.html'), 'utf8')
const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].find(match => match[1].includes('createApp({'))[1]
let options
vm.runInNewContext(script, {
    Vue: { createApp(value) { options = value; return { mount() {} } } },
})

test('static server 405 explains how to open the correct login and registration page', async () => {
    const message = await options.methods.responseErrorMessage({ status: 405 }, '注册失败')
    assert.match(message, /HTTP 405/)
    assert.match(message, /守护脚本显示的网页入口/)
})

test('registration disabled and validation messages from the API remain intact', async () => {
    const disabled = await options.methods.responseErrorMessage({
        status: 403, json: async () => ({ detail: '用户注册当前已关闭，请联系管理员' }),
    }, '注册失败')
    assert.equal(disabled, '用户注册当前已关闭，请联系管理员')
    const invalid = await options.methods.responseErrorMessage({
        status: 422, json: async () => ({ detail: [{ msg: 'Value error, 用户名不符合要求' }] }),
    }, '注册失败')
    assert.equal(invalid, '用户名不符合要求')
})
