<template>
  <view class="page"><view class="title">我的课题</view><view class="muted">每个课题拥有独立的背景、对话和汇报。</view><button class="primary" @tap="edit()">＋ 创建课题</button>
    <view v-if="error" class="card error">{{ error }}<button @tap="load">重试</button></view>
    <view v-for="project in projects" :key="project.id" class="card project"><view class="between"><view class="subtitle">{{ project.name }}</view><text v-if="project.status === 'active'" class="tag">当前</text></view><view class="muted prewrap">{{ project.direction }}</view><view class="muted reference-count">{{ project.references.length }} 篇参考文献</view><view class="actions"><button v-if="project.status !== 'active'" :disabled="busy" @tap="activate(project.id)">切换到此课题</button><button v-else class="primary" @tap="chat(project.id)">每日对话</button><button @tap="edit(project.id)">课题资料</button><button @tap="showDays(project.id)">对话历史</button></view>
      <view v-if="historyId === project.id" class="history"><view v-if="!history.length" class="muted">还没有对话记录，切换到此课题后开始交流。</view><view v-for="day in history" :key="day.occurred_on" class="history-day" @tap="chat(project.id, day.occurred_on)"><view class="between"><text>{{ day.occurred_on }}</text><text class="muted">{{ day.turn_count }} 轮 ›</text></view><view class="muted excerpt">{{ day.excerpt }}</view></view></view>
      <view class="project-footer"><text class="muted">课题编号 #{{ project.id }}</text><button class="delete-project" :data-project-id="project.id" :disabled="deletingId !== null" :loading="deletingId === project.id" @tap.stop="handleDeleteTap">{{ deletingId === project.id ? '正在处理' : '删除课题' }}</button></view>
    </view><view v-if="!projects.length && !busy" class="card empty muted">还没有课题。先建立一份研究背景，开始每天的交流。</view>
  </view>
</template>
<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { toast } from '../../utils/ui'
const projects = ref([]), busy = ref(false), error = ref(''), historyId = ref(null), history = ref([]), deletingId = ref(null)
function edit(id) { uni.navigateTo({ url: '/pages/onboarding/index' + (id ? '?id=' + id : '') }) }
function chat(id, day) { uni.navigateTo({ url: '/pages/chat/index?id=' + id + (day ? '&date=' + day : '') }) }
async function load() { busy.value = true; error.value = ''; try { projects.value = await api.researchProjects() } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } }
async function activate(id) { if (busy.value) return; busy.value = true; try { await api.activate(id); projects.value = await api.researchProjects(); toast('已切换课题') } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } }
async function showDays(id) { if (historyId.value === id) { historyId.value = null; return } try { history.value = await api.conversationDays(id); historyId.value = id } catch (e) { error.value = errorMessage(e) } }
function deletionMessage(preview) {
  const counts = preview.counts
  const lines = [`《${preview.name}》（编号 #${preview.project_id}）`, `将永久删除：${counts.project_references} 篇参考文献、${counts.journal_turns} 轮对话、${counts.reports} 份汇报、${counts.drafts} 份草稿。`]
  if (counts.reference_documents) lines.push(`其中包含 ${counts.reference_documents} 份 PDF 文件及提取正文。`)
  const legacy = [[counts.tasks, '项旧版任务'], [counts.task_logs, '条进展记录'], [counts.literature_notes, '篇文献笔记'], [counts.agent_memory, '条课题记忆']].filter(item => item[0])
  if (legacy.length) lines.push('以及 ' + legacy.map(item => item[0] + ' ' + item[1]).join('、') + '。')
  if (preview.is_current) lines.push(preview.replacement ? `删除后切换到《${preview.replacement.name}》（编号 #${preview.replacement.id}）。` : '这是最后一个课题，删除后可重新创建。')
  lines.push('删除后无法在小程序内恢复。')
  return lines.join('\n')
}
function clearProjectCache(id, taskIds) {
  const keys = new Set([`journal_project_form_${id}`, `journal_report_${id}`, `research_report_${id}`, `research_plan_${id}`, ...taskIds.map(taskId => `research_progress_${taskId}`)])
  try {
    for (const key of uni.getStorageInfoSync().keys) {
      if (keys.has(key) || key.startsWith(`journal_message_${id}_`)) uni.removeStorageSync(key)
    }
  } catch (_) { /* Deletion has succeeded; unavailable local storage must not report it as failed. */ }
}
function handleDeleteTap(event) {
  const id = Number(event.currentTarget?.dataset?.projectId)
  if (!Number.isSafeInteger(id) || id <= 0) { toast('无法识别课题，请重新编译后再试'); return }
  return removeProject(id)
}
async function removeProject(id) {
  if (deletingId.value !== null) return
  if (busy.value) { toast('课题正在加载，请稍后再试'); return }
  busy.value = true; deletingId.value = id; error.value = ''
  uni.showLoading({ title: '核对课题资料', mask: true })
  try {
    const preview = await api.projectDeletionPreview(id)
    uni.hideLoading()
    const confirmed = await new Promise((resolve, reject) => uni.showModal({ title: '确认删除课题？', content: deletionMessage(preview), confirmText: '确认删除', confirmColor: '#bd3948', cancelText: '保留课题', success: result => resolve(result.confirm), fail: reject }))
    if (!confirmed) return
    uni.showLoading({ title: '正在删除课题', mask: true })
    const result = await api.deleteProject(id, { confirmed: true, project_name: preview.name, preview_token: preview.preview_token })
    projects.value = projects.value.filter(item => item.id !== id).map(item => ({ ...item, status: item.id === result.active_project?.id ? 'active' : 'archived' }))
    if (historyId.value === id) { historyId.value = null; history.value = [] }
    clearProjectCache(id, result.task_ids)
    uni.hideLoading()
    toast('课题已删除')
  } catch (e) { uni.hideLoading(); error.value = errorMessage(e); uni.showModal({ title: '暂时无法删除', content: error.value, showCancel: false, confirmText: '知道了' }) }
  finally { uni.hideLoading(); busy.value = false; deletingId.value = null }
}
onShow(load)
</script>
<style scoped>.project{margin-top:24rpx}.project .subtitle{max-width:80%}.reference-count{margin-top:20rpx}.actions button{font-size:25rpx;min-width:150rpx}.history{margin-top:22rpx;border-top:1rpx solid #e9edf5}.history-day{padding:24rpx 0}.excerpt{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.project-footer{display:flex;align-items:center;justify-content:space-between;border-top:1rpx solid #e9edf5;margin-top:22rpx;padding-top:12rpx}.project-footer .delete-project{margin:0;padding:12rpx 0 12rpx 24rpx;min-height:80rpx;font-size:26rpx;background:transparent;color:#bd3948}.delete-project::after{border:0}.delete-project[disabled]{opacity:.45}</style>
