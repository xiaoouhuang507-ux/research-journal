<template>
  <view class="page">
    <view class="card hero"><view class="eyebrow">计划由你做主</view><view class="title">把目标变成下一步行动</view><view class="muted">{{ projectName }} · {{ source === 'llm' ? 'AI 生成建议' : '基础规划建议' }}</view></view>
    <view class="notice">选择要保存的任务，调整名称、时间和产出。确认时保存当前这份内容。</view>
    <view v-if="error" class="card error">{{ error }}<button :disabled="busy" @tap="load">重新加载</button></view>
    <view v-if="busy && !items.length" class="card empty muted">正在整理科研计划，请稍候…</view>
    <view v-for="(item, index) in items" :key="item.key" class="card">
      <view class="between"><view class="subtitle">任务 {{ index + 1 }}</view><switch :checked="item.selected" color="#315fdb" :disabled="saved" @change="item.selected = $event.detail.value" /></view>
      <text class="label">任务名称</text><input v-model="item.name" :disabled="saved" maxlength="300" />
      <text class="label">所属阶段</text><input v-model="item.stage" :disabled="saved" maxlength="100" />
      <text class="label">具体行动</text><textarea v-model="item.description" :disabled="saved" maxlength="5000" />
      <view class="date-row"><view><text class="label">开始日期</text><picker mode="date" :disabled="saved" :value="item.start_date" @change="item.start_date = $event.detail.value"><view class="picker">{{ item.start_date }}</view></picker></view><view><text class="label">截止日期</text><picker mode="date" :disabled="saved" :value="item.deadline" :end="projectDeadline" @change="item.deadline = $event.detail.value"><view class="picker">{{ item.deadline }}</view></picker></view></view>
      <text class="label">优先级</text><picker :range="priorities" :disabled="saved" :value="priorities.indexOf(item.priority)" @change="item.priority = priorities[$event.detail.value]"><view class="picker">{{ item.priority }} ▾</view></picker>
      <text class="label">预期产出</text><input v-model="item.deliverable" :disabled="saved" maxlength="2000" placeholder="例如：小样本结果表" />
      <text class="label">怎样算完成？</text><textarea v-model="item.acceptance_criteria" :disabled="saved" maxlength="2000" placeholder="明确可检查的完成标准" />
      <view v-if="item.conflicts?.length" class="warning">与已有任务时间重叠，请核对可投入时间。</view><view v-if="!saved" class="link danger" @tap="remove(index)">移除此项任务</view>
    </view>
    <button v-if="draftId && !saved" :disabled="busy" @tap="add">＋ 添加一项任务</button>
    <view class="fixed-footer"><button v-if="!saved" class="primary" :disabled="busy || !selectedCount" :loading="busy" @tap="save">确认保存 {{ selectedCount }} 项任务</button><button v-if="saved" class="primary" @tap="viewTasks">查看已保存任务</button><button v-if="draftId && !saved" :disabled="busy" @tap="regenerate">重新生成建议</button></view>
  </view>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { confirmAction, localDate, token, toast } from '../../utils/ui'
const id = ref(''), projectName = ref(''), projectDeadline = ref(''), items = ref([]), draftId = ref(''), source = ref(''), busy = ref(false), saved = ref(false), error = ref('')
const priorities = ['高', '中', '低'], selectedCount = computed(() => items.value.filter(item => item.selected).length)
const storageKey = () => 'research_plan_' + id.value
watch(items, () => { if (draftId.value && !saved.value) uni.setStorageSync(storageKey(), { draft_id: draftId.value, items: items.value }) }, { deep: true })
onLoad(query => { id.value = query.id; load() })
async function load(force = false) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    const projects = await api.projects(), project = projects.find(item => item.id === Number(id.value))
    if (!project || project.status !== 'active') throw new Error('课题已切换，请从当前课题重新进入')
    projectName.value = project.name; projectDeadline.value = project.deadline
    let draft = force === true ? null : await api.planDraft(id.value)
    if (!draft) draft = await api.plan(id.value)
    const local = uni.getStorageSync(storageKey())
    draftId.value = draft.draft_id; source.value = draft.source
    items.value = local?.draft_id === draft.draft_id ? local.items : draft.project_plan.map(item => ({ ...item, key: token(), selected: true }))
  } catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
function viewTasks() { uni.switchTab({ url: '/pages/tasks/index' }) }
function add() { items.value.push({ key: token(), selected: true, name: '', stage: '实验验证', description: '', start_date: localDate(), deadline: projectDeadline.value, priority: '中', deliverable: '', acceptance_criteria: '' }) }
function remove(index) { items.value.splice(index, 1) }
async function regenerate() { if (await confirmAction('重新生成建议', '当前编辑内容将被新的建议替换，是否继续？')) await load(true) }
async function save() {
  if (busy.value || saved.value) return
  const chosen = items.value.filter(item => item.selected)
  if (chosen.some(item => !item.name.trim() || !item.stage.trim() || item.deadline < item.start_date || item.deadline > projectDeadline.value)) { toast('请检查任务名称、阶段和起止日期'); return }
  busy.value = true; error.value = ''
  try { await api.plan(id.value, { confirm: true, draft_id: draftId.value, items: chosen }); saved.value = true; uni.removeStorageSync(storageKey()); toast('计划已保存，可开始记录进展') }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
</script>
<style scoped>.date-row{display:flex;gap:18rpx}.date-row>view{flex:1;min-width:0}.date-row .picker{font-size:24rpx;padding:18rpx 10rpx}</style>
