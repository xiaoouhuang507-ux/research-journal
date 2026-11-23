<template>
  <view class="page">
    <view class="card hero"><view class="eyebrow">日常聊过的，组会用得上</view><view class="title">把这段时间的对话，整理成汇报</view><view class="muted">{{ projectName }} · 仅依据所选日期内你实际说过的内容。</view></view>
    <view class="card"><view class="subtitle">选择汇报范围</view><picker :range="scopes" :value="scopes.indexOf(scope)" :disabled="busy" @change="scope = scopes[$event.detail.value]"><view class="picker">{{ scope }} ▾</view></picker><view v-if="scope === '自定义'" class="date-row"><picker mode="date" :value="start" :end="today" @change="start = $event.detail.value"><view class="picker">{{ start }}</view></picker><text>至</text><picker mode="date" :value="end" :end="today" @change="end = $event.detail.value"><view class="picker">{{ end }}</view></picker></view><button class="primary" :disabled="busy" :loading="busy" @tap="generate">{{ draft ? '按所选范围生成新草稿' : '生成汇报草稿' }}</button></view>
    <view v-if="error" class="card error">{{ error }}</view>
    <view v-if="draft" class="card">
      <view class="between"><view class="subtitle">{{ saved ? '已保存的汇报' : '汇报草稿 · 可以编辑' }}</view><text v-if="!saved" class="link" @tap="editing = !editing">{{ editing ? '预览' : '编辑' }}</text></view>
      <view class="muted">{{ draft.start_date }} 至 {{ draft.end_date }} · {{ draft.sources?.length || 0 }} 条来源</view>
      <textarea v-if="editing" v-model="markdown" class="editor" :disabled="saved" maxlength="100000" auto-height />
      <ReportPreview v-else :content="markdown" />
      <view v-if="!draft.sources?.length" class="warning">所选日期内没有科研对话。请调整日期，或先与 AI 聊聊这段时间做了什么。</view>
      <view class="muted">{{ draft.limitation }}</view>
      <view class="actions"><button :disabled="!markdown" @tap="copy">复制汇报</button><button v-if="!saved" class="primary" :disabled="busy || !markdown.trim()" :loading="busy" @tap="save">确认保存当前内容</button><button v-else :disabled="busy" @tap="revise(savedId)">编辑为新版本</button></view>
      <view v-if="draft.sources?.length" class="divider" /><view v-for="source in draft.sources" :key="source.kind + source.id" class="source"><view class="link" @tap="viewSource(source)">{{ source.kind === 'conversation' ? '科研对话' : source.kind === 'progress' ? '旧版进展记录' : '旧版文献笔记' }} #{{ source.id }} · {{ source.date }} ›</view><view class="muted prewrap">{{ source.accomplishment || source.excerpt || source.result || source.blocker || source.next_step }}</view></view>
    </view>
    <view class="card"><view class="subtitle">历史汇报</view><view v-if="!history.length" class="muted">保存后可在这里查看，修改会保留为新版本。</view><view v-for="report in history" :key="report.id" class="history"><view>{{ report.start_date || report.time_scope }} {{ report.end_date ? '至 ' + report.end_date : '' }}</view><view class="muted">汇报 #{{ report.id }} · {{ report.created_at }}</view><view class="actions"><button size="mini" :disabled="busy" @tap="openHistory(report)">查看</button><button size="mini" :disabled="busy" @tap="revise(report.id)">编辑为新版本</button></view></view></view>
  </view>
</template>
<script setup>
import { ref, watch } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import ReportPreview from '../../components/ReportPreview.vue'
import { api, errorMessage } from '../../utils/api'
import { confirmAction, localDate, openTask, toast } from '../../utils/ui'
const id = ref(''), projectName = ref('科研课题'), scope = ref('自定义'), scopes = ['本周', '近两周', '本月', '自定义'], start = ref(localDate(-6)), end = ref(localDate()), today = localDate()
const draft = ref(null), markdown = ref(''), busy = ref(false), saved = ref(false), savedId = ref(null), editing = ref(false), error = ref(''), history = ref([])
const storageKey = () => 'journal_report_' + id.value
watch([markdown, draft], () => { if (draft.value && !saved.value) uni.setStorageSync(storageKey(), { draft: draft.value, markdown: markdown.value }) })
onLoad(async query => { id.value = query.id; const local = uni.getStorageSync(storageKey()); if (local) { draft.value = local.draft; markdown.value = local.markdown } try { const results = await Promise.all([api.reports(id.value), api.projectProfile(id.value)]); history.value = results[0]; projectName.value = results[1].name } catch (e) { error.value = errorMessage(e) } })
async function canReplace() { return !draft.value || saved.value || await confirmAction('替换当前草稿', '当前未保存的编辑将被替换，是否继续？') }
function setDraft(result) { draft.value = result; markdown.value = result.markdown; saved.value = false; savedId.value = null; editing.value = false }
async function generate() {
  if (busy.value || !(await canReplace())) return
  busy.value = true; error.value = ''
  try { setDraft(await api.report(id.value, { time_scope: scope.value, start_date: scope.value === '自定义' ? start.value : undefined, end_date: scope.value === '自定义' ? end.value : undefined })) }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function save() {
  if (busy.value || saved.value) return
  busy.value = true; error.value = ''
  try { const result = await api.report(id.value, { save: true, draft_id: draft.value.draft_id, markdown: markdown.value }); markdown.value = result.markdown; saved.value = true; savedId.value = result.report_id; editing.value = false; uni.removeStorageSync(storageKey()); history.value = await api.reports(id.value); toast('已保存你确认的内容') }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function openHistory(report) { if (!(await canReplace())) return; draft.value = { ...report, sources: JSON.parse(report.sources || '[]') }; markdown.value = report.content; saved.value = true; savedId.value = report.id; editing.value = false }
async function revise(reportId) {
  if (busy.value || !(await canReplace())) return
  busy.value = true; error.value = ''
  try { setDraft(await api.reviseReport(id.value, reportId)); editing.value = true }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
function copy() { uni.setClipboardData({ data: markdown.value, success: () => toast('汇报已复制') }) }
function viewSource(source) { if (source.kind === 'conversation') uni.navigateTo({ url: '/pages/chat/index?id=' + id.value + '&date=' + source.date }); else if (source.kind === 'progress') openTask(source.task_id); else uni.navigateTo({ url: '/pages/notes/index' }) }
</script>
<style scoped>.date-row{display:flex;gap:10rpx;align-items:center}.date-row picker{flex:1;min-width:0}.date-row .picker{font-size:23rpx;padding:18rpx 8rpx}.editor{min-height:640rpx;margin-top:22rpx}.source,.history{border-bottom:1rpx solid #edf0f5;padding:20rpx 0}.source:last-child,.history:last-child{border:0}</style>
