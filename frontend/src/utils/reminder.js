import { api } from './api'
let interval = null, active = false, checking = false
async function check() {
  if (!active || checking) return
  const pages = getCurrentPages()
  if (pages[pages.length - 1]?.route === 'pages/chat/index') return
  checking = true
  try {
    const state = await api.reminder()
    if (active && state.due) {
      const result = await api.claimReminder()
      if (active && result.show) uni.showModal({ title: '留两分钟，记下今天的科研', content: '今天做了什么，或者遇到了什么问题？和 AI 简短聊一聊，为下次组会留下素材。', confirmText: '现在聊聊', cancelText: '稍后再说', success: async response => { if (response.confirm) { const home = await api.home().catch(() => null); if (home?.project) uni.navigateTo({ url: '/pages/chat/index?id=' + home.project.id }) } } })
    }
  } catch (_) { /* Connection errors are shown on the current page. */ }
  finally { checking = false }
}
export function startReminders() { active = true; clearInterval(interval); setTimeout(check, 1000); interval = setInterval(check, 30000) }
export function stopReminders() { active = false; clearInterval(interval); interval = null }
