const { test } = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const { parse, compileScript } = require('@vue/compiler-sfc')
const { transformSync } = require('esbuild')
const vue = require('vue')

function mountPage(name, api, options = {}) {
  const storage = new Map(), navigation = [], loadHandlers = [], showHandlers = [], modals = []
  api = { projectProfile: async () => ({ name: '测试课题' }), ...api }
  const uni = {
    getStorageSync: key => storage.get(key), setStorageSync: (key, value) => storage.set(key, JSON.parse(JSON.stringify(value))),
    removeStorageSync: key => storage.delete(key), showToast() {}, showLoading() {}, hideLoading() {}, pageScrollTo() {},
    getStorageInfoSync: () => ({ keys: [...storage.keys()] }),
    showModal: data => { modals.push(data); data.success?.({ confirm: options.confirmDelete !== false }) },
    redirectTo: data => navigation.push(data.url), switchTab: data => navigation.push(data.url), navigateTo: data => navigation.push(data.url), navigateBack() {}
  }
  const filename = path.join(__dirname, '../src/pages', name, 'index.vue')
  const descriptor = parse(fs.readFileSync(filename, 'utf8')).descriptor
  const script = compileScript(descriptor, { id: name }).content
  const code = transformSync(script, { format: 'cjs', loader: 'js' }).code
  const sandbox = { module: { exports: {} }, uni, console, require: id => {
    if (id === 'vue') return vue
    if (id === '@dcloudio/uni-app') return { onLoad: callback => loadHandlers.push(callback), onShow: callback => showHandlers.push(callback) }
    if (id.endsWith('/api')) return { api, errorMessage: error => error.message }
    if (id.endsWith('/ui')) return { token: () => 'test-token', localDate: () => '2026-10-19', toast() {}, confirmAction: async () => true, openTask() {} }
    if (id.endsWith('.vue')) return { default: {} }
    throw new Error('Unexpected import ' + id)
  } }
  vm.runInNewContext(code, sandbox, { filename })
  const state = sandbox.module.exports.default.setup({}, { expose() {} })
  return { state, storage, navigation, modals, load: query => loadHandlers.forEach(handler => handler(query)), show: () => showHandlers.forEach(handler => handler()) }
}
const settle = async () => { for (let i = 0; i < 6; i++) await new Promise(resolve => setImmediate(resolve)) }
const item = name => ({ stage: '实验验证', name, description: '', start_date: '2026-10-19', deadline: '2026-10-22', priority: '中', deliverable: '实验记录', acceptance_criteria: '' })

test('PDF reference upload fills the form and preserves document identity when saving without notes', async () => {
  const calls = []
  const reference = { title: '自动识别的标题', authors: '', year: '', url: '', notes: '', document_id: 'd'.repeat(32), document: { sha256: 'a'.repeat(64), filename: 'paper.pdf', page_count: 2, readable_pages: 2, char_count: 900 } }
  const page = mountPage('onboarding', {
    uploadReference: async () => reference,
    saveProject: async (...args) => { calls.push(args); return { project_id: 4 } }
  })
  page.load({}); await settle()
  Object.assign(page.state.form, { name: '课题', topic: '主题', direction: '方向' })
  await page.state.uploadPDF(); await settle()
  assert.equal(page.state.form.references[0].title, '自动识别的标题')
  assert.equal(page.state.form.references[0].notes, '')
  assert.equal(page.storage.get('journal_project_form_new').references[0].document_id, reference.document_id)
  await page.state.create()
  assert.equal(calls[0][1].references[0].document_id, reference.document_id)
  assert.equal(page.navigation[0], '/pages/chat/index?id=4')
})

test('upload cancellation and failure preserve references and an in-flight upload blocks save', async () => {
  let complete
  const page = mountPage('onboarding', { uploadReference: () => new Promise(resolve => { complete = resolve }), saveProject: async () => { throw new Error('Must not save during upload') } })
  page.load({}); await settle()
  Object.assign(page.state.form, { name: '课题', topic: '主题', direction: '方向' })
  const task = page.state.uploadPDF()
  assert.equal(page.state.uploading.value, true)
  await page.state.create()
  complete({ title: '标题', document_id: 'd'.repeat(32), document: { sha256: 'a' } })
  await task
  assert.equal(page.state.uploading.value, false)
  const cancelled = mountPage('onboarding', { uploadReference: async () => { throw { cancelled: true } } })
  cancelled.load({}); await settle(); await cancelled.state.uploadPDF()
  assert.equal(cancelled.state.error.value, '')
  const failed = mountPage('onboarding', { uploadReference: async () => { throw new Error('扫描版无法提取正文') } })
  failed.load({}); await settle(); await failed.state.uploadPDF()
  assert.equal(failed.state.form.references.length, 0)
  assert.equal(failed.modals[0].content, '扫描版无法提取正文')
})

test('plan page saves edited selected tasks under the preview identifier and prevents repeat submission', async () => {
  const calls = []
  const page = mountPage('plan', {
    projects: async () => [{ id: 1, name: '测试课题', status: 'active', deadline: '2026-11-30' }],
    planDraft: async () => ({ draft_id: 'draft-one', project_plan: [item('任务甲'), item('任务乙')] }),
    plan: async (...args) => { calls.push(args); return { saved: true } }
  })
  page.load({ id: '1' }); await settle()
  page.state.items.value[0].name = '编辑后的任务'
  page.state.items.value[1].selected = false
  await page.state.save(); await settle(); await page.state.save()
  assert.equal(calls.length, 1)
  assert.equal(calls[0][1].draft_id, 'draft-one')
  assert.equal(calls[0][1].items.length, 1)
  assert.equal(calls[0][1].items[0].name, '编辑后的任务')
  assert.equal(page.state.saved.value, true)
  assert.equal(page.storage.has('research_plan_1'), false)
})

test('plan local edits survive leaving and reloading the same draft', async () => {
  const page = mountPage('plan', {
    projects: async () => [{ id: 1, name: '课题', status: 'active', deadline: '2026-11-30' }],
    planDraft: async () => ({ draft_id: 'same-draft', project_plan: [item('原始建议')] })
  })
  page.load({ id: '1' }); await settle()
  page.state.items.value[0].name = '未保存的修改'; await settle()
  await page.state.load(); await settle()
  assert.equal(page.state.items.value[0].name, '未保存的修改')
})

test('report saves edited text and original draft even if the date selector has changed', async () => {
  const calls = []
  const draft = { draft_id: 'report-one', markdown: '# 原草稿', start_date: '2026-10-19', end_date: '2026-10-19', sources: [] }
  const page = mountPage('report', {
    reports: async () => [],
    report: async (_id, body) => { calls.push(body); return body.save ? { ...draft, report_id: 9, markdown: body.markdown } : draft }
  })
  page.load({ id: '1' }); await settle()
  await page.state.generate()
  page.state.markdown.value = '# 用户修改的汇报\n\n实际结果已核对'
  page.state.scope.value = '本月'
  await page.state.save(); await settle(); await page.state.save()
  assert.equal(calls.length, 2)
  assert.equal(calls[1].draft_id, 'report-one')
  assert.equal(calls[1].markdown, '# 用户修改的汇报\n\n实际结果已核对')
  assert.equal(page.state.savedId.value, 9)
  assert.equal(page.storage.has('research_report_1'), false)
})

test('progress request failure retains text and retry identifier', async () => {
  const task = { id: 3, name: '实验', status: '进行中', progress: 20, project_status: 'active', deadline: '2026-10-22', logs: [] }
  const page = mountPage('task-detail', { task: async () => task, progress: async () => { throw new Error('连接中断') } })
  page.load({ id: '3' }); await settle()
  page.state.form.value.accomplishment = '已经完成的数据检查'
  const key = page.state.form.value.client_token
  await page.state.saveProgress(); await settle()
  assert.equal(page.state.error.value, '连接中断')
  assert.equal(page.state.form.value.accomplishment, '已经完成的数据检查')
  assert.equal(page.state.form.value.client_token, key)
  assert.equal(page.storage.get('research_progress_3').accomplishment, '已经完成的数据检查')
})

test('creating a project requires topic and direction, saves references and opens daily conversation', async () => {
  const calls = []
  const page = mountPage('onboarding', { saveProject: async (_id, body) => { calls.push(body); return { project_id: 8 } } })
  await page.state.create()
  assert.equal(calls.length, 0)
  page.state.form.name = '我的课题'; page.state.form.topic = '多标签学习'; page.state.form.direction = '比较两种特征选择方法'
  page.state.addReference(); page.state.form.references[0].title = '论文甲'
  await page.state.create()
  assert.equal(calls.length, 1)
  assert.equal(calls[0].references[0].title, '论文甲')
  assert.equal(page.navigation[0], '/pages/chat/index?id=8')
})

test('daily conversation retains failed input and reuses the same retry token', async () => {
  const calls = []
  const page = mountPage('chat', { conversation: async () => ({ project: { id: 1, status: 'active' }, turns: [], ai_available: true }), sendDaily: async (_id, body) => { calls.push({ ...body }); throw new Error('网络中断') } })
  page.load({ id: '1' }); await settle()
  page.state.text.value = '今天完成数据检查'
  await page.state.send(); await page.state.send()
  assert.equal(page.state.text.value, '今天完成数据检查')
  assert.equal(calls[0].client_token, calls[1].client_token)
  assert.equal(page.storage.get('journal_message_1_2026-10-19').text, '今天完成数据检查')
})

test('retrying a saved failed turn does not send a second user message', async () => {
  const failed = { id: 7, client_token: 'saved-token', user_content: '今天读论文', occurred_on: '2026-10-19', status: 'failed' }
  const calls = []
  const page = mountPage('chat', { conversation: async () => ({ project: { id: 1, status: 'active' }, turns: [failed], ai_available: true }), sendDaily: async (_id, body) => { calls.push(body); return { ...failed, status: 'complete', assistant_content: '什么方法与你课题相关？' } } })
  page.load({ id: '1' }); await settle()
  await page.state.send()
  assert.equal(calls[0].client_token, 'saved-token')
  assert.equal(page.state.turns.value.length, 1)
  assert.equal(page.state.turns.value[0].status, 'complete')
})

test('report conversation sources open the matching project and day', async () => {
  const page = mountPage('report', { reports: async () => [] })
  page.load({ id: '8' }); await settle()
  page.state.viewSource({ kind: 'conversation', id: 5, date: '2026-10-18' })
  assert.equal(page.navigation[0], '/pages/chat/index?id=8&date=2026-10-18')
})

const deletionPreview = {
  project_id: 1, name: '同名课题', is_current: true, preview_token: 'snapshot-token', replacement: { id: 10, name: '同名课题' },
  counts: { project_references: 1, journal_turns: 2, reports: 3, drafts: 4, tasks: 1, task_logs: 1, literature_notes: 1, agent_memory: 1 }
}

test('cancelling project deletion retains every record and local draft', async () => {
  const calls = []
  const page = mountPage('projects', {
    projectDeletionPreview: async () => deletionPreview,
    deleteProject: async (...args) => calls.push(args)
  }, { confirmDelete: false })
  page.state.projects.value = [{ id: 1, name: '同名课题', status: 'active' }]
  page.storage.set('journal_report_1', '未保存的汇报')
  await page.state.handleDeleteTap({ currentTarget: { dataset: { projectId: '1' } } })
  assert.equal(calls.length, 0)
  assert.equal(page.state.projects.value.length, 1)
  assert.equal(page.storage.get('journal_report_1'), '未保存的汇报')
  assert.equal(page.state.busy.value, false)
})

test('confirmed deletion switches current project and clears only deleted project caches', async () => {
  const calls = []
  const page = mountPage('projects', {
    projectDeletionPreview: async id => { assert.equal(id, 1); return deletionPreview },
    deleteProject: async (...args) => { calls.push(args); return { task_ids: [7], active_project: { id: 10, name: '同名课题' } } }
  })
  page.state.projects.value = [{ id: 1, name: '同名课题', status: 'active' }, { id: 10, name: '同名课题', status: 'archived' }]
  page.state.historyId.value = 1; page.state.history.value = [{ occurred_on: '2026-10-20' }]
  const deleted = ['journal_project_form_1', 'journal_report_1', 'research_report_1', 'research_plan_1', 'journal_message_1_2026-10-20', 'research_progress_7']
  const retained = ['journal_message_10_2026-10-20', 'journal_report_10', 'research_progress_70', 'journal_project_form_new', 'research_server_url']
  for (const key of [...deleted, ...retained]) page.storage.set(key, '保留的输入')
  await page.state.handleDeleteTap({ currentTarget: { dataset: { projectId: '1' } } })
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 1)
  assert.equal(calls[0][1].confirmed, true)
  assert.equal(calls[0][1].preview_token, 'snapshot-token')
  assert.equal(calls[0][1].project_name, '同名课题')
  assert.equal(page.state.projects.value.length, 1)
  assert.equal(page.state.projects.value[0].id, 10)
  assert.equal(page.state.projects.value[0].status, 'active')
  assert.equal(page.state.historyId.value, null)
  assert.equal(page.state.history.value.length, 0)
  for (const key of deleted) assert.equal(page.storage.has(key), false, key)
  for (const key of retained) assert.equal(page.storage.has(key), true, key)
  const modal = page.modals[0]
  assert.match(modal.content, /编号 #1/)
  assert.match(modal.content, /2 轮对话、3 份汇报/)
  assert.match(modal.content, /1 项旧版任务/)
  assert.match(modal.content, /编号 #10/)
  assert.match(modal.content, /无法在小程序内恢复/)
})

test('deletion failure preserves list and unsaved content for retry', async () => {
  const page = mountPage('projects', {
    projectDeletionPreview: async () => deletionPreview,
    deleteProject: async () => { throw new Error('资料已变化，请重新核对') }
  })
  page.state.projects.value = [{ id: 1, name: '同名课题', status: 'active' }]
  page.storage.set('journal_message_1_2026-10-20', '未发送的内容')
  await page.state.handleDeleteTap({ currentTarget: { dataset: { projectId: '1' } } })
  assert.equal(page.state.projects.value.length, 1)
  assert.equal(page.state.error.value, '资料已变化，请重新核对')
  assert.equal(page.storage.get('journal_message_1_2026-10-20'), '未发送的内容')
  assert.equal(page.state.busy.value, false)
  assert.equal(page.modals.at(-1).title, '暂时无法删除')
  assert.equal(page.modals.at(-1).content, '资料已变化，请重新核对')
})
