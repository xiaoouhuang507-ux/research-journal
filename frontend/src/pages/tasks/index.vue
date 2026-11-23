<template>
  <view class="page">
    <view class="title">让研究向前一步</view><view class="muted">{{ project?.name || '先创建课题，再安排科研任务' }}</view>
    <view class="filters"><text v-for="item in filters" :key="item" :class="['filter', filter === item ? 'active' : '']" @tap="filter = item">{{ item }}</text></view>
    <view v-if="error" class="card error">{{ error }}<button @tap="load">重试</button></view>
    <view v-if="busy" class="card empty muted">正在读取任务…</view>
    <view v-for="task in visible" :key="task.id" class="card" @tap="openTask(task.id)">
      <view class="between"><text class="tag">{{ task.stage }}</text><text :class="['priority', task.priority === '高' ? 'danger' : 'muted']">{{ task.priority }}优先级</text></view>
      <view class="task-name">{{ task.name || task.description }}</view><view class="muted">{{ task.start_date }} 至 {{ task.deadline }}</view>
      <view class="progress"><view class="bar" :style="{ width: task.progress + '%' }" /></view><view class="between"><text class="muted">{{ task.status }} · 完成 {{ task.progress }}%</text><text class="link">记录进展 →</text></view>
      <view class="muted">产出：{{ task.deliverable || '待补充' }}</view><view v-if="task.blocker" class="warning">阻碍：{{ task.blocker }}</view><view v-else-if="task.deadline < today && task.status !== '已完成'" class="warning">已超过截止日期，可记录原因并调整安排。</view>
    </view>
    <view v-if="!busy && !error && !visible.length" class="card empty"><view class="subtitle">{{ tasks.length ? '当前筛选下没有任务' : '从一份可执行的计划开始' }}</view><view class="muted">{{ tasks.length ? '切换筛选可查看其他任务。' : '你可以修改建议，再确认保存要推进的任务。' }}</view></view>
    <button v-if="project" class="primary" @tap="plan">生成／继续编辑计划</button><button v-else @tap="onboard">创建我的课题</button>
  </view>
</template>
<script setup>
import { computed, ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { localDate, openTask } from '../../utils/ui'
const tasks = ref([]), project = ref(null), busy = ref(false), error = ref(''), filter = ref('全部'), today = localDate()
const filters = ['全部', '未开始', '进行中', '遇到阻碍', '已完成', '延期']
const visible = computed(() => filter.value === '全部' ? tasks.value : tasks.value.filter(task => filter.value === '延期' ? (task.status === '延期' || (task.deadline < today && task.status !== '已完成')) : task.status === filter.value))
function plan() { uni.navigateTo({ url: '/pages/plan/index?id=' + project.value.id }) }
function onboard() { uni.navigateTo({ url: '/pages/onboarding/index' }) }
async function load() { if (busy.value) return; busy.value = true; error.value = ''; try { const dashboard = await api.dashboard(); project.value = dashboard.active_project; tasks.value = project.value ? await api.tasks(project.value.id) : [] } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } }
onShow(load)
</script>
<style scoped>.filters{display:flex;gap:12rpx;overflow:auto;padding:24rpx 0}.filter{white-space:nowrap;background:#fff;padding:10rpx 20rpx;border-radius:30rpx;font-size:25rpx}.active{background:#315fdb;color:#fff}.task-name{font-size:30rpx;font-weight:650;margin:16rpx 0 8rpx}.priority{font-size:23rpx}</style>
