<template>
  <view class="page"><view class="title">我的</view><view v-if="error" class="card error">{{ error }}<button @tap="load">重试</button></view>
    <view class="card"><view class="subtitle">每日科研提醒</view><view class="between"><view>每天提醒我聊一聊</view><switch :checked="reminder.enabled" color="#315fdb" @change="reminder.enabled = $event.detail.value" /></view><view class="muted">今天已有记录时，不再发送当天提醒。时间按北京时间。</view><text class="label">提醒时间</text><picker mode="time" :value="reminder.reminder_time" @change="reminder.reminder_time = $event.detail.value"><view class="picker">每天 {{ reminder.reminder_time }} ▾</view></picker><button class="primary" :disabled="busy" @tap="saveReminder">保存提醒设置</button>
      <view class="divider" /><view class="subtitle">微信服务通知</view><view v-if="!reminder.wechat?.configured" class="muted">尚未开通微信外部提醒。当前支持打开小程序时的到点提示；开通后可在微信收到通知。</view><template v-else><view class="muted">{{ reminder.wechat.ready ? (reminder.wechat.subscription_kind === 'longterm' ? '已授权每日提醒。' : '已授权一次提醒，等待下次发送。') : '尚无可用的订阅授权。' }}</view><view class="muted">{{ reminder.wechat.subscription_kind === 'longterm' ? '当前使用长期订阅模板，每天到点提醒；后端需保持运行。' : '微信一次性订阅每次授权可接收一条提醒。用完后需再次点击授权；后端需保持运行。' }}</view><button :disabled="busy || !reminder.enabled" @tap="authorize">{{ reminder.wechat.subscription_kind === 'longterm' ? '授权每日微信提醒' : '授权下一次微信提醒' }}</button></template><view v-if="reminder.wechat?.last_error" class="warning">{{ reminder.wechat.last_error }}</view>
    </view>
    <view class="card"><view class="subtitle">AI 连接状态</view><view :class="aiAvailable ? 'notice' : 'warning'">{{ aiAvailable ? '已配置 AI 模型，可测试连接后开始对话。' : '尚未配置模型，当前使用基础追问和原始对话整理。' }}</view><button :disabled="busy" :loading="busy" @tap="checkAi">测试 AI 连接</button><view v-if="aiConnection" class="notice">{{ aiConnection }}</view><view class="muted">模型密钥由后端管理。上传 PDF 后，AI 可依据带页码的正文段落分析；仅手动录入的文献仍依据笔记，链接不会自动读取。</view></view>
    <view class="card"><view class="subtitle">服务连接</view><view class="muted">电脑预览使用本机地址；手机预览需要电脑可访问的局域网地址。</view><text class="label">服务地址</text><input v-model="baseUrl" placeholder="http://127.0.0.1:8000" /><button :disabled="busy" @tap="saveConnection">保存地址并检查连接</button><view v-if="connection" class="notice">{{ connection }}</view></view>
  </view>
</template>
<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api, errorMessage, serverUrl } from '../../utils/api'
import { toast } from '../../utils/ui'
const busy = ref(false), error = ref(''), baseUrl = ref(serverUrl()), connection = ref(''), aiAvailable = ref(false)
const reminder = ref({ enabled: true, reminder_time: '20:00', wechat: {} })
const aiConnection = ref('')
async function checkAi() { if (busy.value) return; busy.value = true; try { const result = await api.checkAi(); aiConnection.value = result.message } catch (e) { aiConnection.value = errorMessage(e) } finally { busy.value = false } }
async function load() { if (busy.value) return; busy.value = true; error.value = ''; try { const data = await api.home(); reminder.value = data.reminder; aiAvailable.value = data.ai_available } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } }
async function saveReminder() { if (busy.value) return; busy.value = true; error.value = ''; try { reminder.value = await api.saveReminder({ enabled: reminder.value.enabled, reminder_time: reminder.value.reminder_time }); toast('提醒设置已保存') } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } }
async function authorize() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try {
    // The platform subscription prompt must be invoked directly from the user's tap.
    const template = reminder.value.wechat.template_id
    const result = await new Promise((resolve, reject) => uni.requestSubscribeMessage({ tmplIds: [template], success: resolve, fail: reject }))
    if (result[template] !== 'accept') { toast('未授权微信提醒，可继续使用站内提醒'); return }
    const login = await new Promise((resolve, reject) => uni.login({ provider: 'weixin', success: resolve, fail: reject }))
    const identity = await api.wechatLogin(login.code)
    reminder.value = await api.subscribe({ device_token: identity.device_token, template_id: template }); toast('已授权下一次微信提醒')
  } catch (e) { error.value = e.errMsg || errorMessage(e) } finally { busy.value = false }
}
async function saveConnection() { const url = baseUrl.value.trim().replace(/\/+$/, ''); if (!/^https?:\/\/[^\s]+$/.test(url)) { toast('请填写有效的服务地址'); return } uni.setStorageSync('research_server_url', url); connection.value = ''; await load(); connection.value = error.value ? '连接失败，请检查地址和后端服务。' : '连接成功，可以开始每日对话。' }
onShow(load)
</script>
