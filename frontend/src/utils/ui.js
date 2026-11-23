export function localDate(offset = 0) {
  return new Date(Date.now() + 8 * 3600000 + offset * 86400000).toISOString().slice(0, 10)
}
export const token = () => Date.now() + '-' + Math.random().toString(36).slice(2)
export const taskUrl = id => '/pages/task-detail/index?id=' + id
export const openTask = id => uni.navigateTo({ url: taskUrl(id) })
export const toast = title => uni.showToast({ title, icon: 'none' })
export function confirmAction(title, content) {
  return new Promise(resolve => uni.showModal({ title, content, success: result => resolve(result.confirm), fail: () => resolve(false) }))
}
