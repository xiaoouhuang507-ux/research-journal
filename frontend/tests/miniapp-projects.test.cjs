// Exercise WXML event bindings and the compiled request adapter, not only setup methods.
const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { ref } = require('vue')

const projects = [{ id: 3, name: '当前课题', direction: '研究方向', status: 'active', references: [] }, { id: 2, name: '旧课题', direction: '历史方向', status: 'archived', references: [] }]
const preview = { project_id: 2, name: '旧课题', is_current: false, preview_token: 'a'.repeat(64), counts: { project_references: 0, journal_turns: 0, reports: 1, drafts: 2, tasks: 1, task_logs: 1, literature_notes: 0, agent_memory: 0 } }

function mountCompiledPage(variant, options = {}) {
  const root = path.join(__dirname, '../dist', variant, 'mp-weixin')
  const requests = [], modals = [], loading = [], toasts = [], handlers = new Map(), showHandlers = [], storage = new Map()
  let component, eventIndex = 0
  const uni = {
    getStorageSync: key => storage.get(key), getStorageInfoSync: () => ({ keys: [...storage.keys()] }),
    removeStorageSync: key => storage.delete(key),
    showLoading: data => loading.push(data.title), hideLoading: () => loading.push('hidden'),
    showToast: data => toasts.push(data.title),
    showModal: data => { modals.push(data); data.success?.({ confirm: options.confirm !== false }) },
    request(data) {
      requests.push(data)
      if (data.url.endsWith('/deletion-preview')) {
        if (options.networkError) return data.fail({ errMsg: 'request:fail timeout' })
        return data.success({ statusCode: 200, data: preview })
      }
      if (data.method === 'DELETE') return data.success({ statusCode: 200, data: { task_ids: [7], active_project: { id: 3, name: '当前课题' } } })
      if (data.url.endsWith('/api/v2/projects')) return data.success({ statusCode: 200, data: projects })
      throw new Error('Unexpected request ' + data.url)
    }
  }
  const vendor = { ref, index: uni, e: Object.assign, f: (items, callback) => items.map(callback), t: String,
    onShow: callback => showHandlers.push(callback), _export_sfc: item => item,
    o: (handler, key) => { const name = 'e' + eventIndex++ + '_' + key; handlers.set(name, handler); return name }
  }
  function readModule(filename, dependencies) {
    const sandbox = { module: { exports: {} }, exports: {}, console, wx: { createPage: item => { component = item } },
      require: name => {
        if (!(name in dependencies)) throw new Error('Unexpected import ' + name)
        return dependencies[name]
      }
    }
    sandbox.exports = sandbox.module.exports
    vm.runInNewContext(fs.readFileSync(path.join(root, filename), 'utf8'), sandbox, { filename })
    return sandbox.exports
  }
  const api = readModule('utils/api.js', { '../common/vendor.js': vendor })
  readModule('pages/projects/index.js', { '../../common/vendor.js': vendor, '../../utils/api.js': api, '../../utils/ui.js': { toast: title => toasts.push(title) } })
  const render = component.setup()
  const template = fs.readFileSync(path.join(root, 'pages/projects/index.wxml'), 'utf8')
  const loop = template.match(/wx:for="{{([^}]+)}}" wx:for-item="([^"]+)"/)
  const buttonMatch = template.match(/(<button\b[^>]*class="[^"]*\bdelete-project\b[^"]*"[^>]*>)([\s\S]*?)<\/button>/)
  const button = buttonMatch?.[1]
  assert.ok(button, 'Compiled page must contain delete button')
  function renderData() {
    eventIndex = 0
    const data = render({}, {})
    if (options.staleScript) {
      for (const card of data[loop[1]]) {
        // This is the exact old-render/new-template mismatch in the screenshot:
        // the previous render stored its tap identifier in the current label slot.
        card.o = 'e4_3'
        delete card.r
      }
    }
    return data
  }
  function value(expression, data, card) {
    const parts = expression.replace(/^{{|}}$/g, '').trim().split('.')
    return parts[0] === loop[2] ? parts.slice(1).reduce((item, key) => item[key], card) : parts.reduce((item, key) => item[key], data)
  }
  async function tapDelete(id) {
    const data = renderData(), card = data[loop[1]].find(item => Object.values(item).includes(String(id)))
    assert.ok(card, 'The requested card must be rendered')
    const label = buttonMatch[2].replace(/{{([^}]+)}}/g, (_, expression) => value(expression, data, card)).trim()
    assert.equal(label, '删除课题', 'Button text must match the current script/template pair')
    const binding = button.match(/(?:bindtap|catchtap)="([^"]+)"/)[1]
    const dataset = button.match(/data-project-id="([^"]+)"/)[1]
    const disabled = button.match(/disabled="([^"]+)"/)[1]
    assert.equal(value(disabled, data, card), false, 'Delete button must be enabled before click')
    await handlers.get(value(binding, data, card))({ currentTarget: { dataset: { projectId: value(dataset, data, card) } }, stopPropagation() {} })
  }
  return { requests, modals, loading, toasts, storage, show: async () => { for (const handler of showHandlers) await handler() }, tapDelete, renderData }
}

for (const variant of ['dev', 'build']) {
  test(`${variant}: stale script/template pair is detected before simulating a click`, async () => {
    const page = mountCompiledPage(variant, { staleScript: true })
    await page.show()
    await assert.rejects(page.tapDelete(2), /Button text must match/)
    assert.equal(page.requests.some(item => item.method === 'DELETE'), false)
  })
  test(`${variant}: tapping compiled delete button loads preview and cancelling keeps project`, async () => {
    const page = mountCompiledPage(variant, { confirm: false })
    await page.show(); await page.tapDelete(2)
    assert.ok(page.loading.includes('核对课题资料'))
    assert.equal(page.modals.length, 1)
    assert.equal(page.modals[0].title, '确认删除课题？')
    assert.match(page.modals[0].content, /编号 #2/)
    assert.equal(page.requests.at(-1).url, 'http://127.0.0.1:8000/api/v2/projects/2/deletion-preview')
    assert.equal(page.requests.at(-1).timeout, 10000)
    assert.equal(page.requests.some(item => item.method === 'DELETE'), false)
  })

  test(`${variant}: confirming compiled delete button submits the preview and refreshes rendered list`, async () => {
    const page = mountCompiledPage(variant)
    await page.show(); await page.tapDelete(2)
    const request = page.requests.find(item => item.method === 'DELETE')
    assert.equal(request.url, 'http://127.0.0.1:8000/api/v2/projects/2')
    assert.equal(request.data.confirmed, true)
    assert.equal(request.data.project_name, preview.name)
    assert.equal(request.data.preview_token, preview.preview_token)
    assert.ok(page.toasts.includes('课题已删除'))
    assert.ok(page.loading.includes('正在删除课题'))
    const cards = Object.values(page.renderData()).find(Array.isArray)
    assert.equal(cards.length, 1)
    assert.ok(Object.values(cards[0]).includes('当前课题'))
  })

  test(`${variant}: network failure shows an immediate explanation and keeps delete available`, async () => {
    const page = mountCompiledPage(variant, { networkError: true })
    await page.show(); await page.tapDelete(2)
    assert.equal(page.modals[0].title, '暂时无法删除')
    assert.equal(page.modals[0].content, 'request:fail timeout')
    assert.equal(page.requests.some(item => item.method === 'DELETE'), false)
    await page.tapDelete(2)
    assert.equal(page.modals.length, 2)
  })
}
