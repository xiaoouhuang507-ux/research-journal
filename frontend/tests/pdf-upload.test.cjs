const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const vue = require('vue')

for (const variant of ['dev', 'build']) {
  for (const failed of [false, true]) {
    test(`${variant} compiled PDF button selects, uploads and renders ${failed ? 'a readable failure' : 'the extracted reference'}`, async () => {
      const root = path.join(__dirname, '../dist', variant, 'mp-weixin')
      const handlers = new Map(), loads = [], requests = [], modals = [], storage = new Map()
      let page, sequence = 0, selected = false
      const wx = { createPage: component => { page = component }, chooseMessageFile: options => {
        selected = true
        assert.equal(options.extension[0], 'pdf')
        options.success({ tempFiles: [{ name: 'reference.pdf', path: '/tmp/chosen.pdf', size: 1000 }] })
      } }
      const uni = {
        getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, value), removeStorageSync: key => storage.delete(key),
        showModal: options => modals.push(options),
        uploadFile: options => {
          requests.push(options)
          assert.equal(options.name, 'file')
          assert.equal(options.filePath, '/tmp/chosen.pdf')
          assert.equal(options.formData.filename, 'reference.pdf')
          options.success({ statusCode: failed ? 422 : 200, data: JSON.stringify(failed ? { detail: '扫描版无法提取正文' } : {
            title: 'Parsed PDF Title', document_id: 'd'.repeat(32), authors: '', year: '', url: '', notes: '',
            document: { sha256: 'a'.repeat(64), filename: 'reference.pdf', readable_pages: 2, page_count: 2, char_count: 3500, warning: '请核对原文' }
          }) })
        }
      }
      const vendor = { ...vue, index: uni, wx$1: wx, e: Object.assign, t: String, f: (items, callback) => items.map(callback),
        onLoad: callback => loads.push(callback), _export_sfc: component => component,
        o: handler => { const id = 'event-' + sequence++; handlers.set(id, handler); return id }
      }
      function read(filename, dependencies) {
        const sandbox = { module: { exports: {} }, exports: {}, wx, console, require: name => {
          if (!(name in dependencies)) throw new Error('Unexpected import ' + name)
          return dependencies[name]
        } }
        sandbox.exports = sandbox.module.exports
        vm.runInNewContext(fs.readFileSync(path.join(root, filename), 'utf8'), sandbox, { filename })
        return sandbox.exports
      }
      const api = read('utils/api.js', { '../common/vendor.js': vendor })
      read('pages/onboarding/index.js', { '../../common/vendor.js': vendor, '../../utils/api.js': api,
        '../../utils/ui.js': { toast() {}, confirmAction: async () => true } })
      const render = page.setup()
      await loads[0]({})
      const template = fs.readFileSync(path.join(root, 'pages/onboarding/index.wxml'), 'utf8')
      const uploadButton = [...template.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map(match => match[0]).find(button => /class="[^"]*\bpdf-upload\b/.test(button))
      assert.ok(uploadButton)
      assert.match(uploadButton, /data-eventsync="true"/, 'File selection must run in the original user tap, without the Vue event delay')
      assert.doesNotMatch(uploadButton.split('>')[0], /wx:if=/, 'Keep the upload entry visible even at the reference limit')
      const eventKey = uploadButton.match(/bindtap="{{([^}]+)}}"/)[1]
      await handlers.get(render({}, {})[eventKey])()
      assert.equal(selected, true)
      assert.equal(requests.length, 1)
      const after = render({}, {})
      if (failed) {
        assert.equal(modals[0].content, '扫描版无法提取正文')
        assert.equal(storage.has('journal_project_form_new'), false)
      } else {
        assert.ok(JSON.stringify(after).includes('Parsed PDF Title'))
        assert.ok(JSON.stringify(after).includes('reference.pdf'))
        assert.equal(storage.get('journal_project_form_new').references[0].document_id, 'd'.repeat(32))
      }
    })
  }

  test(`${variant}: unsupported WeChat file selection reports failure instead of calling the H5 placeholder`, async () => {
    const root = path.join(__dirname, '../dist', variant, 'mp-weixin')
    let fallbackCalled = false
    const vendor = { wx$1: {}, index: { chooseFile() { fallbackCalled = true } } }
    const module = { exports: {} }
    vm.runInNewContext(fs.readFileSync(path.join(root, 'utils/api.js'), 'utf8'), {
      module, exports: module.exports, require: () => vendor
    })
    await assert.rejects(module.exports.api.uploadReference(), error => /不支持选择 PDF/.test(error.message))
    assert.equal(fallbackCalled, false)
  })

  test(`${variant}: a conversation with zero PDFs still offers a visible upload entry for its own project`, async () => {
    const root = path.join(__dirname, '../dist', variant, 'mp-weixin')
    const loads = [], navigation = [], handlers = new Map()
    let component, sequence = 0
    const vendor = { ...vue, nextTick$1: vue.nextTick, index: { getStorageSync() {}, navigateTo: options => navigation.push(options.url) },
      e: Object.assign, t: String, f: (items, callback) => items.map(callback),
      onLoad: handler => loads.push(handler), onShow() {}, _export_sfc: value => value,
      o: handler => { const key = 'tap-' + sequence++; handlers.set(key, handler); return key }
    }
    const api = { errorMessage: error => { throw error }, api: { conversation: async id => ({ project: { id, name: '没有 PDF 的课题', status: 'active', references: [] }, turns: [], ai_available: true }) } }
    vm.runInNewContext(fs.readFileSync(path.join(root, 'pages/chat/index.js'), 'utf8'), {
      wx: { createPage: value => { component = value } }, console,
      require: name => ({ '../../common/vendor.js': vendor, '../../utils/api.js': api,
        '../../utils/ui.js': { localDate: () => '2026-10-21', token: () => 'test-token' } })[name]
    })
    const render = component.setup()
    await loads[0]({ id: '12' })
    const template = fs.readFileSync(path.join(root, 'pages/chat/index.wxml'), 'utf8')
    const row = template.match(/<view\b[^>]*class="[^"]*\breference-entry\b[^>]*>[\s\S]*?<\/button>/)?.[0]
    assert.ok(row, 'The upload entry belongs in the fixed header, outside the scrollable chat history')
    const data = render({}, {})
    const condition = row.match(/wx:if="{{([^}]+)}}"/)
    if (condition) assert.ok(data[condition[1]], 'The entry is visible without any existing PDF')
    const button = row.match(/<button\b[^>]*>[\s\S]*?<\/button>/)[0]
    assert.match(button, />上传 PDF<\/button>/)
    const binding = button.match(/bindtap="{{([^}]+)}}"/)[1]
    handlers.get(data[binding])()
    assert.equal(navigation[0], '/pages/onboarding/index?id=12')
  })
}
