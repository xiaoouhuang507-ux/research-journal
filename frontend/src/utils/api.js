const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'
export const serverUrl = () => uni.getStorageSync('research_server_url') || DEFAULT_BASE_URL
export function errorMessage(error) {
  if (typeof error === 'string') return error
  const detail = error?.detail
  if (Array.isArray(detail)) return detail.map(item => item.msg).join('；')
  return detail?.message || detail || error?.message || error?.errMsg || '暂时无法连接服务，请检查连接地址后重试'
}
export function request(path, method = 'GET', data, timeout = 60000) {
  return new Promise((resolve, reject) => uni.request({
    url: serverUrl() + path, method, data, timeout,
    success: response => response.statusCode < 400 ? resolve(response.data) : reject(response.data), fail: reject
  }))
}
function sessionId() {
  let id = uni.getStorageSync('research_session')
  if (!id) { id = 'session-' + Date.now() + '-' + Math.random().toString(36).slice(2); uni.setStorageSync('research_session', id) }
  return id
}
export function chooseReferencePDF() {
  return new Promise((resolve, reject) => {
    const success = result => {
      const file = result.tempFiles?.[0]
      if (!file) { reject({ cancelled: true }); return }
      if (!/\.pdf$/i.test(file.name || '')) { reject({ message: '请选择 PDF 文件' }); return }
      if (file.size > 10 * 1024 * 1024) { reject({ message: 'PDF 不能超过 10 MB，请压缩或拆分后上传' }); return }
      resolve({ path: file.path || result.tempFilePaths?.[0], name: file.name })
    }
    const fail = error => reject(/cancel/i.test(error.errMsg || '') ? { cancelled: true } : error)
    // WeChat has no uni.chooseFile implementation. Do not call a placeholder
    // function there: it may never invoke a callback and leave the form busy.
    if (typeof wx !== 'undefined') {
      if (typeof wx.chooseMessageFile !== 'function') { reject({ message: '当前微信环境不支持选择 PDF，请更新开发者工具或使用微信手机端重试' }); return }
      wx.chooseMessageFile({ count: 1, type: 'file', extension: ['pdf'], success, fail })
    } else if (typeof uni.chooseFile === 'function') uni.chooseFile({ count: 1, type: 'all', extension: ['.pdf'], success, fail })
    else reject({ message: '当前环境无法选择文件，请在微信开发者工具或微信中打开' })
  })
}
export function uploadReferencePDF(file) {
  return new Promise((resolve, reject) => uni.uploadFile({
    url: serverUrl() + '/api/v2/references/pdf', filePath: file.path, name: 'file',
    formData: { filename: file.name }, timeout: 60000,
    success: response => {
      let data
      try { data = JSON.parse(response.data) } catch (_) { reject({ message: '上传服务返回异常，请检查后端是否已更新' }); return }
      if (response.statusCode >= 200 && response.statusCode < 300) resolve(data)
      else reject(data)
    }, fail: reject
  }))
}
export function openReferencePDF(id) {
  return new Promise((resolve, reject) => uni.downloadFile({
    url: serverUrl() + '/api/v2/references/pdf/' + encodeURIComponent(id),
    success: result => {
      if (result.statusCode !== 200) { reject({ message: 'PDF 不存在或已移除，请重新打开课题资料' }); return }
      uni.openDocument({ filePath: result.tempFilePath, fileType: 'pdf', showMenu: true, success: resolve, fail: reject })
    }, fail: reject
  }))
}
export const api = {
  uploadReference: async () => uploadReferencePDF(await chooseReferencePDF()),
  openReference: openReferencePDF,
  home: () => request('/api/v2/home'),
  checkAi: () => request('/api/v2/ai/check', 'POST'),
  researchProjects: () => request('/api/v2/projects'),
  projectProfile: id => request(`/api/v2/projects/${id}`),
  saveProject: (id, data) => request('/api/v2/projects' + (id ? '/' + id : ''), id ? 'PUT' : 'POST', data),
  projectDeletionPreview: id => request(`/api/v2/projects/${id}/deletion-preview`, 'GET', undefined, 10000),
  deleteProject: (id, data) => request(`/api/v2/projects/${id}`, 'DELETE', data),
  conversation: (id, day) => request(`/api/v2/projects/${id}/conversation?occurred_on=${day}`),
  sendDaily: (id, data) => request(`/api/v2/projects/${id}/conversation`, 'POST', data),
  conversationDays: id => request(`/api/v2/projects/${id}/days`),
  reminder: () => request('/api/v2/reminder'),
  saveReminder: data => request('/api/v2/reminder', 'PUT', data),
  claimReminder: () => request('/api/v2/reminder/claim', 'POST'),
  wechatLogin: code => request('/api/v2/reminder/wechat-login', 'POST', { code }),
  subscribe: data => request('/api/v2/reminder/subscribe', 'POST', data),
  dashboard: () => request('/api/v1/dashboard'),
  chat: message => request('/api/chat', 'POST', { message, session_id: sessionId() }),
  confirm: action => request('/api/chat/confirm', 'POST', { action, session_id: sessionId() }),
  projects: () => request('/api/v1/projects'), addProject: data => request('/api/v1/projects', 'POST', data),
  demoProject: () => request('/api/v1/demo-project', 'POST'), activate: id => request(`/api/v1/projects/${id}/activate`, 'POST'),
  plan: (id, data = {}) => request(`/api/v1/projects/${id}/plan`, 'POST', data), planDraft: id => request(`/api/v1/projects/${id}/plan-draft`),
  tasks: projectId => request('/api/v1/tasks' + (projectId ? `?project_id=${projectId}` : '')),
  task: id => request(`/api/v1/tasks/${id}`), patchTask: (id, data) => request(`/api/v1/tasks/${id}`, 'PUT', data),
  progress: (id, data) => request(`/api/v1/tasks/${id}/progress`, 'POST', data), riskAction: (id, data) => request(`/api/v1/tasks/${id}/risk-action`, 'POST', data),
  warnings: () => request('/api/warnings'), risk: id => request(`/api/v1/projects/${id}/risk`, 'POST'),
  report: (id, data = {}) => request(`/api/v2/projects/${id}/report`, 'POST', data), reports: id => request(`/api/v1/projects/${id}/reports`),
  reviseReport: (id, reportId) => request(`/api/v2/projects/${id}/reports/${reportId}/revision`, 'POST'),
  notes: () => request('/api/v1/literatures'), previewNote: data => request('/api/v1/literatures/analyze-preview', 'POST', data), addNote: data => request('/api/v1/literatures', 'POST', data),
  preferences: () => request('/api/v1/preferences'), savePreferences: data => request('/api/v1/preferences', 'PATCH', data)
}
