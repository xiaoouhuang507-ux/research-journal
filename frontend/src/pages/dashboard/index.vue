<template>
  <view class="page">
    <view class="greeting"><view class="eyebrow">RESEARCH JOURNAL</view><view class="title">把今天的一小步，<view>留给下次组会。</view></view><view class="muted">{{ today }} · 每天聊几句，科研过程有迹可循</view></view>
    <view v-if="error" class="card error">{{ error }}<button @tap="load">重新连接</button><button @tap="settings">连接设置</button></view>
    <view v-if="busy && !loaded" class="card empty muted">正在翻开你的科研日记…</view>
    <view v-if="loaded && !data.project" class="card welcome"><view class="welcome-icon">研</view><view class="subtitle">先让 AI 认识你的课题</view><view class="muted">写下研究主题、具体方向和参考文献。以后每天告诉 AI 今天做了什么，它会接着问，帮你留下汇报素材。</view><button class="primary" @tap="create">创建我的课题</button></view>
    <template v-if="data.project">
      <view class="card hero"><view class="between"><text class="eyebrow">当前课题</text><text class="small-link" @tap="projects">切换 / 编辑</text></view><view class="subtitle">{{ data.project.name }}</view><view class="muted clamp">{{ data.project.direction }}</view><view class="hero-meta">{{ data.project.references.length }} 篇参考文献 · 已记录 {{ data.recorded_days }} 天</view></view>
      <view class="card daily"><view class="between"><view class="subtitle">{{ data.today_turns ? '今天的故事，还可以接着聊' : '今天的科研，进展如何？' }}</view><text class="tag">{{ data.today_turns ? '已记录' : '待记录' }}</text></view><view class="muted">不用填表，一两句话就能开始。AI 会结合你的课题和此前的交流继续追问。</view><button class="primary" @tap="chat()">{{ data.today_turns ? '继续今天的对话' : '告诉 AI 今天做了什么' }}</button><view class="daily-meta">{{ data.reminder?.enabled ? '每天 ' + data.reminder.reminder_time + ' 提醒记录' : '每日提醒已关闭' }}<text class="link" @tap="settings">设置</text></view></view>
      <view v-if="!data.ai_available" class="notice">当前为基础追问模式。接入模型后可获得结合完整课题背景的 AI 追问与汇报归纳。<text class="link" @tap="settings">查看连接状态</text></view>
      <view class="card"><view class="between"><view class="subtitle">最近的科研对话</view><text class="link" @tap="projects">全部记录 →</text></view><view v-if="!data.days.length" class="empty muted">第一条记录，从今天开始。</view><view v-for="day in data.days" :key="day.occurred_on" class="day" @tap="chat(day.occurred_on)"><view class="between"><text>{{ day.occurred_on }}</text><text class="muted">{{ day.turn_count }} 轮交流 ›</text></view><view class="muted clamp">{{ day.excerpt }}</view></view></view>
      <view class="card report-entry" @tap="reports"><view><view class="subtitle">组会前，交给这些日常记录</view><view class="muted">选择日期，将这段时间的对话整理成汇报</view></view><text class="arrow">→</text></view>
    </template>
  </view>
</template>
<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { localDate } from '../../utils/ui'
const data = ref({ project: null, days: [] }), busy = ref(false), loaded = ref(false), error = ref(''), today = ref(localDate())
function create() { uni.navigateTo({ url: '/pages/onboarding/index' }) }
function settings() { uni.switchTab({ url: '/pages/settings/index' }) }
function projects() { uni.switchTab({ url: '/pages/projects/index' }) }
function reports() { uni.navigateTo({ url: '/pages/report/index?id=' + data.value.project.id }) }
function chat(day) { uni.navigateTo({ url: '/pages/chat/index?id=' + data.value.project.id + '&date=' + (day || today.value) }) }
async function load() { if (busy.value) return; busy.value = true; error.value = ''; today.value = localDate(); try { data.value = await api.home(); loaded.value = true } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } }
onShow(load)
</script>
<style scoped>
.greeting{padding:22rpx 4rpx 36rpx}.greeting .eyebrow{color:#607ea9;font-size:21rpx;letter-spacing:5rpx}.greeting .title{font-size:46rpx;line-height:1.5}.small-link{font-size:23rpx;color:#e4edff}.hero-meta{font-size:23rpx;margin-top:22rpx;color:#dce7ff}.clamp{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.daily{padding:32rpx}.daily .subtitle{max-width:78%;font-size:31rpx}.daily button{margin-top:30rpx}.daily-meta{display:flex;justify-content:space-between;color:#8894a6;font-size:23rpx;margin-top:20rpx}.day{padding:24rpx 0;border-bottom:1rpx solid #edf0f5}.day:last-child{border:0}.day .muted{margin-top:8rpx}.report-entry{display:flex;align-items:center;justify-content:space-between;background:#edf3ff}.arrow{color:#315fdb;font-size:42rpx}.welcome{text-align:center;padding:42rpx 30rpx}.welcome-icon{width:90rpx;height:90rpx;line-height:90rpx;background:#eaf0ff;border-radius:24rpx;margin:0 auto 24rpx;color:#315fdb;font-size:42rpx;font-weight:700}
</style>
