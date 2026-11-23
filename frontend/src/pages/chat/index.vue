<template>
  <view class="chat-page">
    <view class="chat-header"><view class="between"><view class="project-name">{{ project?.name || '每日科研对话' }}</view><text class="link" @tap="openReport">生成汇报</text></view><view class="between"><picker mode="date" :value="day" :end="today" :disabled="busy" @change="changeDay($event.detail.value)"><view class="date-picker">{{ day === today ? '今天 · ' : '' }}{{ day }} ▾</view></picker><text class="muted">对话自动保存</text></view><view v-if="project" class="between reference-entry"><text class="muted">{{ pdfCount ? '已关联 ' + pdfCount + ' 份 PDF，可结合正文分析' : '上传参考文献，让 AI 结合正文分析' }}</text><button class="reference-upload" :disabled="busy" @tap="openProfile">上传 PDF</button></view></view>
    <scroll-view scroll-y class="history" :scroll-into-view="lastId" scroll-with-animation>
      <view class="history-inner">
        <view v-if="pdfCount" class="notice">已关联 {{ pdfCount }} 份 PDF，AI 可结合相关正文分析并注明页码。<text class="link" @tap="openProfile"> 查看课题资料 ›</text></view>
        <view v-if="project && !aiAvailable" class="notice">基础追问模式 · 模型尚未接入。记录会保存，接入模型后可继续交流。</view>
        <view v-if="project?.status !== 'active' && project" class="notice">这是历史课题的对话。继续记录前，请在“课题”中切换到此课题。</view>
        <view v-if="!turns.length && !loading" class="intro"><view class="avatar">研</view><view class="subtitle">今天做了什么？从一句话开始。</view><view class="muted">读了一篇论文、跑了一次实验，或遇到了一个问题，都可以告诉我。我会结合你的研究方向，帮你把细节问清楚。</view><view class="starter" @tap="starter('今天读了一篇文献，')">今天读了一篇文献…</view><view class="starter" @tap="starter('今天做了一个实验，')">今天做了一个实验…</view><view class="starter" @tap="starter('今天遇到一个问题，')">今天遇到一个问题…</view></view>
        <view v-for="turn in turns" :id="'turn-' + turn.id" :key="turn.id" class="turn"><view class="speaker user-speaker">我</view><view class="bubble user prewrap">{{ turn.user_content }}</view><template v-if="turn.assistant_content"><view class="speaker">{{ turn.ai_mode === 'model' ? '科研 AI' : '基础追问' }}</view><view class="bubble assistant prewrap">{{ turn.assistant_content }}</view></template><view v-else class="pending muted">{{ busy ? '正在结合课题思考…' : '你的发言已保存，等待 AI 回复' }}</view></view>
        <view v-if="pendingText" class="turn"><view class="speaker user-speaker">我</view><view class="bubble user prewrap">{{ pendingText }}</view><view class="muted pending">正在结合课题思考…</view></view>
        <view v-if="error" class="error chat-error">{{ error }}<button v-if="retryTurn" size="mini" :disabled="busy" @tap="send">重试 AI 回复</button><button v-else size="mini" :disabled="busy" @tap="load">刷新对话</button></view><view id="chat-bottom" class="bottom-anchor" />
      </view>
    </scroll-view>
    <view class="composer"><view v-if="day !== today" class="muted backfill">正在补记 {{ day }} 的科研记录</view><textarea v-model="text" :disabled="busy || !!retryTurn || project?.status !== 'active'" maxlength="8000" :auto-height="true" :adjust-position="true" :show-confirm-bar="false" placeholder="简短说说今天做了什么…" /><view class="between"><text class="muted">{{ retryTurn ? '先重试上一条回复，即可继续交流' : 'AI 可能有误，汇报前请核对' }}</text><button class="primary" :disabled="busy || loading || (!text.trim() && !retryTurn) || project?.status !== 'active'" :loading="busy" @tap="send">{{ retryTurn ? '重试回复' : '发送' }}</button></view></view>
  </view>
</template>
<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { onLoad, onShow } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { localDate, token } from '../../utils/ui'
const id = ref(''), project = ref(null), day = ref(localDate()), today = ref(localDate()), turns = ref([]), aiAvailable = ref(false)
const text = ref(''), requestToken = ref(token()), busy = ref(false), loading = ref(false), error = ref(''), pendingText = ref(''), lastId = ref('chat-bottom')
const retryTurn = computed(() => turns.value.find(turn => turn.status !== 'complete'))
const pdfCount = computed(() => project.value?.references?.filter(reference => reference.document_id).length || 0)
const storageKey = () => 'journal_message_' + id.value + '_' + day.value
watch(text, () => { if (id.value) uni.setStorageSync(storageKey(), { text: text.value, token: requestToken.value }) }, { flush: 'sync' })
function restore() { const local = uni.getStorageSync(storageKey()); requestToken.value = local?.token || token(); text.value = local?.text || '' }
async function bottom() { lastId.value = ''; await nextTick(); lastId.value = 'chat-bottom' }
async function load() {
  if (!id.value || loading.value) return
  loading.value = true
  try { const result = await api.conversation(id.value, day.value); project.value = result.project; turns.value = result.turns; aiAvailable.value = result.ai_available; const recovered = turns.value.find(turn => turn.client_token === requestToken.value); if (recovered) { requestToken.value = token(); text.value = ''; uni.removeStorageSync(storageKey()) } await bottom() }
  catch (e) { error.value = errorMessage(e) } finally { loading.value = false }
}
async function send() {
  if (busy.value || loading.value || (!text.value.trim() && !retryTurn.value)) return
  const retry = retryTurn.value
  const body = retry ? { message: retry.user_content, occurred_on: retry.occurred_on, client_token: retry.client_token } : { message: text.value.trim(), occurred_on: day.value, client_token: requestToken.value }
  busy.value = true; error.value = ''; pendingText.value = retry ? '' : body.message; await bottom()
  try { const result = await api.sendDaily(id.value, body); if (retry) turns.value = turns.value.filter(turn => turn.id !== retry.id); if (!turns.value.some(turn => turn.id === result.id)) turns.value.push(result); requestToken.value = token(); text.value = ''; uni.removeStorageSync(storageKey()) }
  catch (e) { error.value = errorMessage(e); await load() }
  finally { pendingText.value = ''; busy.value = false; await bottom() }
}
async function changeDay(value) { if (busy.value || loading.value) return; day.value = value; turns.value = []; error.value = ''; restore(); await load() }
function starter(value) { text.value = value }
function openReport() { uni.navigateTo({ url: '/pages/report/index?id=' + id.value }) }
function openProfile() { if (id.value && !busy.value) uni.navigateTo({ url: '/pages/onboarding/index?id=' + id.value }) }
onLoad(async query => { id.value = query.id || ''; day.value = query.date || localDate(); restore(); await load() })
onShow(() => { today.value = localDate(); if (id.value && !busy.value) load() })
</script>
<style scoped>
.chat-page{height:calc(100vh - var(--window-top, 0px));display:flex;flex-direction:column;background:#f5f7fb;box-sizing:border-box}.chat-header{padding:22rpx 28rpx 14rpx;background:#fff;border-bottom:1rpx solid #e9edf5}.project-name{font-weight:650;max-width:72%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.date-picker{font-size:24rpx;color:#64758f;padding:14rpx 0}.history{flex:1;min-height:0;height:0}.history-inner{padding:26rpx}.intro{padding:36rpx 14rpx}.avatar{width:72rpx;height:72rpx;line-height:72rpx;text-align:center;background:#315fdb;color:#fff;border-radius:20rpx;font-size:33rpx;margin-bottom:25rpx}.intro .subtitle{font-size:31rpx}.starter{padding:20rpx;background:#fff;border:1rpx solid #e3e9f5;border-radius:14rpx;margin-top:16rpx;color:#536b91;font-size:25rpx}.speaker{font-size:22rpx;color:#8090a5;margin:18rpx 0 8rpx}.user-speaker{text-align:right}.bubble{padding:24rpx;border-radius:20rpx;max-width:89%;font-size:28rpx;line-height:1.8;box-sizing:border-box}.assistant{background:#fff;border-top-left-radius:4rpx}.user{background:#315fdb;color:#fff;margin-left:auto;border-top-right-radius:4rpx}.pending{padding:20rpx 0}.composer{padding:18rpx 26rpx calc(18rpx + env(safe-area-inset-bottom));background:#fff;border-top:1rpx solid #e5ebf5}.composer textarea{min-height:86rpx;max-height:240rpx;padding:18rpx;line-height:1.6}.composer button{margin:0;min-width:145rpx;flex-shrink:0}.composer .muted{font-size:21rpx}.backfill{margin-bottom:10rpx}.chat-error{padding:20rpx;border-radius:14rpx;margin-top:16rpx}.bottom-anchor{height:20rpx}
</style>
<style scoped>.reference-entry{border-top:1rpx solid #edf0f5;padding-top:14rpx}.reference-entry .muted{font-size:22rpx;flex:1}.reference-upload{margin:0;padding:0 20rpx;flex-shrink:0;font-size:24rpx;line-height:2.5}</style>
