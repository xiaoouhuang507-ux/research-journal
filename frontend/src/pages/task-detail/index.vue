<template>
  <view class="page">
    <view v-if="error" class="card error">{{ error }}<button v-if="!task" @tap="load">重试</button></view>
    <view v-if="!task && busy" class="card empty muted">正在读取任务…</view>
    <template v-if="task">
      <view class="card hero"><view class="eyebrow">{{ task.stage }}</view><view class="title">{{ task.name }}</view><view class="muted">{{ task.status }} · 完成 {{ task.progress }}% · {{ task.deadline }} 截止</view></view>
      <view v-if="archived" class="notice">这是历史课题的资料。可在“我的”中切换到该课题后继续记录。</view>
      <view class="card">
        <view class="between"><view class="subtitle">任务要求</view><text class="link" @tap="editing = !editing">{{ editing ? '收起' : '编辑任务' }}</text></view>
        <view v-if="!editing"><view class="prewrap">{{ task.description || '暂无行动说明' }}</view><view class="label">预期产出</view><view>{{ task.deliverable || '待补充' }}</view><view class="label">完成标准</view><view>{{ task.acceptance_criteria || '待补充' }}</view></view>
        <view v-else>
          <text class="label">任务名称</text><input v-model="edit.name" maxlength="300" />
          <text class="label">行动说明</text><textarea v-model="edit.description" maxlength="5000" />
          <text class="label">截止日期</text><picker mode="date" :value="edit.deadline" :end="task.project_deadline" @change="edit.deadline = $event.detail.value"><view class="picker">{{ edit.deadline }}</view></picker>
          <text class="label">优先级</text><picker :range="priorities" :value="priorities.indexOf(edit.priority)" @change="edit.priority = priorities[$event.detail.value]"><view class="picker">{{ edit.priority }} ▾</view></picker>
          <text class="label">预期产出</text><input v-model="edit.deliverable" maxlength="2000" /><text class="label">完成标准</text><textarea v-model="edit.acceptance_criteria" maxlength="2000" />
          <button class="primary" :disabled="busy || archived" @tap="saveTask">保存任务修改</button>
        </view>
      </view>
      <view id="progress-panel" class="card">
        <view class="subtitle">记录一次科研进展</view><view class="muted">一次有效尝试、失败结果或新的阻碍，都值得记录。</view>
        <text class="label">实际发生日期</text><picker mode="date" :value="form.occurred_on" :end="today" @change="form.occurred_on = $event.detail.value"><view class="picker">{{ form.occurred_on }} ▾</view></picker>
        <text class="label">完成了什么？</text><textarea v-model="form.accomplishment" maxlength="5000" placeholder="例如：完成 50 条样本的工具调用检查" />
        <text class="label">观察到什么结果？</text><textarea v-model="form.result" maxlength="5000" placeholder="填写实际结果、指标或失败现象；没有结果可以留空" />
        <text class="label">遇到什么阻碍？</text><textarea v-model="form.blocker" maxlength="3000" placeholder="例如：数据集尚未拿到，无法运行完整实验" />
        <text class="label">下一步怎么做？</text><textarea v-model="form.next_step" maxlength="3000" placeholder="例如：先用小样本验证数据处理流程" />
        <text class="label">任务状态</text><picker :range="statuses" :value="statuses.indexOf(form.status)" @change="form.status = statuses[$event.detail.value]"><view class="picker">{{ form.status }} ▾</view></picker>
        <text class="label">任务完成比例：{{ form.status === '已完成' ? 100 : form.progress }}%</text><slider :value="form.progress" :disabled="form.status === '已完成'" :step="5" show-value activeColor="#315fdb" @change="form.progress = $event.detail.value" />
        <button class="primary" :disabled="busy || archived" :loading="busy" @tap="saveProgress">保存本次进展</button><view class="muted">输入内容会暂存在本机。较早日期的补录不覆盖最新任务状态。</view>
      </view>
      <view id="risk-panel" class="card">
        <view class="subtitle">调整后续安排</view><view v-if="task.blocker" class="warning">当前阻碍：{{ task.blocker }}</view><view class="muted">先记录阻碍，再核对可交付范围。你可以预览调整后的日期和优先级。</view>
        <text class="label">希望调整到的截止日期</text><picker mode="date" :start="today" :end="task.project_deadline" :value="riskDeadline" @change="riskDeadline = $event.detail.value; proposal = null"><view class="picker">{{ riskDeadline || '由助手建议一个日期' }} ▾</view></picker>
        <button :disabled="busy || archived || task.status === '已完成'" @tap="previewRisk">预览调整建议</button>
        <view v-if="proposal" class="notice">
          <view>截止时间：{{ proposal.before.deadline }} → {{ proposal.after.deadline }}</view><view>优先级：{{ proposal.before.priority }} → {{ proposal.after.priority }}</view><view>{{ proposal.reason }}</view>
          <view v-if="proposal.conflicts.length" class="warning">与 {{ proposal.conflicts.length }} 项任务时间重叠，请核对工作量。</view>
          <button class="primary" :disabled="busy || archived" @tap="applyRisk">确认采用这份调整</button><button :disabled="busy" @tap="proposal = null">暂不调整</button>
        </view>
      </view>
      <view class="card"><view class="subtitle">进展时间线</view><view v-if="!task.logs.length" class="muted">还没有记录，从今天的一次尝试开始。</view>
        <view v-for="log in task.logs" :key="log.id" class="timeline"><view class="between"><text class="tag">{{ log.occurred_on }}</text><text class="muted">{{ log.status }} · {{ log.progress }}%</text></view><view v-if="log.accomplishment" class="prewrap">进展：{{ log.accomplishment }}</view><view v-if="log.result" class="prewrap">结果：{{ log.result }}</view><view v-if="log.blocker" class="prewrap danger">阻碍：{{ log.blocker }}</view><view v-if="log.next_step" class="prewrap">下一步：{{ log.next_step }}</view></view>
      </view>
    </template>
  </view>
</template>
<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { localDate, token, toast } from '../../utils/ui'
const id = ref(''), task = ref(null), busy = ref(false), error = ref(''), editing = ref(false), edit = ref({}), form = ref({}), proposal = ref(null), riskDeadline = ref(''), today = localDate()
const statuses = ['未开始', '进行中', '遇到阻碍', '已完成', '延期'], priorities = ['高', '中', '低'], archived = computed(() => task.value?.project_status !== 'active')
const storageKey = () => 'research_progress_' + id.value
watch(form, () => { if (form.value.client_token) uni.setStorageSync(storageKey(), form.value) }, { deep: true })
function initialForm(t) { return { client_token: token(), occurred_on: localDate(), accomplishment: '', result: '', blocker: t.blocker || '', next_step: '', progress: t.progress, status: t.status } }
function setTask(t) { task.value = t; edit.value = { name: t.name, description: t.description, deadline: t.deadline, priority: t.priority, deliverable: t.deliverable, acceptance_criteria: t.acceptance_criteria } }
onLoad(query => { id.value = query.id; load(query.focus) })
async function load(focus) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { const t = await api.task(id.value); setTask(t); form.value = uni.getStorageSync(storageKey()) || initialForm(t); await nextTick(); if (focus === 'risk') uni.pageScrollTo({ selector: '#risk-panel', duration: 300 }) }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function saveProgress() {
  if (busy.value) return
  if (![form.value.accomplishment, form.value.result, form.value.blocker, form.value.next_step].some(text => text.trim())) { toast('至少填写一项进展、结果、阻碍或下一步'); return }
  if (form.value.status === '遇到阻碍' && !form.value.blocker.trim()) { toast('请说明遇到的阻碍'); return }
  busy.value = true; error.value = ''
  try { await api.progress(id.value, form.value); setTask(await api.task(id.value)); form.value = initialForm(task.value); proposal.value = null; toast('进展已保存，可用于组会汇报') }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function saveTask() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await api.patchTask(id.value, edit.value); setTask(await api.task(id.value)); editing.value = false; proposal.value = null; toast('任务已更新') }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function previewRisk() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { proposal.value = await api.riskAction(id.value, { deadline: riskDeadline.value || undefined }) }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
async function applyRisk() {
  if (busy.value || !proposal.value) return
  busy.value = true; error.value = ''
  try { await api.riskAction(id.value, { confirm: true, draft_id: proposal.value.draft_id }); setTask(await api.task(id.value)); proposal.value = null; toast('已应用确认后的调整') }
  catch (e) { error.value = errorMessage(e); proposal.value = null } finally { busy.value = false }
}
</script>
<style scoped>.timeline{border-left:4rpx solid #dce5f7;padding:0 0 26rpx 20rpx;margin-top:24rpx}.timeline .between{margin-bottom:12rpx}</style>
