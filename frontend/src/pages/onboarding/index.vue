<template>
  <view class="page">
    <view class="card hero"><view class="eyebrow">{{ id ? '课题资料' : '从了解你的研究开始' }}</view><view class="title">{{ id ? '让 AI 更了解你的课题' : '建立课题，开始每天的交流' }}</view><view class="muted">研究背景越清楚，追问越具体。资料随时可以补充。</view></view>
    <view v-if="error" class="card error">{{ error }}</view>
    <view class="card"><text class="label">课题名称 *</text><input v-model="form.name" maxlength="150" placeholder="例如：多标签特征选择研究" /><text class="label">研究主题 *</text><input v-model="form.topic" maxlength="1000" placeholder="例如：面向高维数据的多标签特征选择" /><text class="label">具体研究方向 *</text><textarea v-model="form.direction" class="direction" maxlength="6000" placeholder="想研究什么问题？目前采用什么方法？已有基础是什么？例如：比较两种特征选择方法，在公开数据集上验证分类效果。" /></view>
    <view class="card"><view class="between"><view class="subtitle">参考文献</view><text class="muted">{{ form.references.length }} / 50 篇</text></view><view class="muted">上传 PDF 后自动识别标题并提取正文，无需手动填写摘要。可先创建课题，再补充。</view>
      <button class="primary pdf-upload" data-eventsync="true" :disabled="busy || uploading || form.references.length >= 50" :loading="uploading" @tap="uploadPDF">{{ uploading ? '正在选择或读取 PDF…' : '＋ 上传参考文献 PDF' }}</button>
      <view v-if="form.references.length >= 50" class="muted">已达到 50 篇上限，移除一篇文献后可继续上传。</view>
      <view class="muted upload-help">单份不超过 10 MB、80 页。微信端从聊天文件中选择。聊天时，相关正文会发送给你配置的 AI 服务。</view>
      <view v-for="(reference, index) in form.references" :key="reference.document_id || 'manual-' + index" class="reference"><view class="between"><text class="label">文献 {{ index + 1 }}</text><text class="link danger" @tap="removeReference(index)">移除</text></view>
        <view v-if="reference.document" class="pdf-info"><view class="pdf-name">PDF · {{ reference.document.filename }}</view><view>已提取 {{ reference.document.readable_pages }} / {{ reference.document.page_count }} 页正文 · 约 {{ reference.document.char_count }} 字符</view><view class="muted">{{ reference.document.warning }}</view><button size="mini" :disabled="openingPdf" @tap="viewPDF(reference)">查看原 PDF</button><view class="muted">标题已自动填入，可修改识别结果；作者、年份和笔记均可留空。</view></view>
        <input v-model="reference.title" maxlength="500" placeholder="文献标题 *" /><view class="reference-row"><input v-model="reference.authors" maxlength="500" placeholder="作者（选填）" /><input v-model="reference.year" maxlength="20" placeholder="年份（选填）" /></view><input v-model="reference.url" maxlength="2000" placeholder="论文链接 / DOI 地址（选填）" /><textarea v-model="reference.notes" maxlength="6000" :placeholder="reference.document_id ? '补充你的阅读笔记（选填，无需粘贴摘要）' : '摘要、阅读笔记、可借鉴的方法（选填）'" /></view>
      <button v-if="form.references.length < 50" :disabled="busy || uploading" @tap="addReference">手动添加文献（可选）</button>
    </view>
    <view v-if="!id" class="notice">创建后可直接开始对话。原有课题和记录会保留在“课题”中。</view><button class="primary" :disabled="busy || uploading" :loading="busy" @tap="create">{{ id ? '保存课题资料' : '创建课题，开始对话' }}</button>
  </view>
</template>
<script setup>
import { reactive, ref, watch } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
import { confirmAction, toast } from '../../utils/ui'
const id = ref(''), busy = ref(false), error = ref(''), ready = ref(false)
const uploading = ref(false), openingPdf = ref(false)
const form = reactive({ name: '', topic: '', direction: '', references: [] })
const storageKey = () => 'journal_project_form_' + (id.value || 'new')
watch(form, () => { if (ready.value) uni.setStorageSync(storageKey(), JSON.parse(JSON.stringify(form))) }, { deep: true })
onLoad(async query => { id.value = query.id || ''; busy.value = true; try { if (id.value) { const project = await api.projectProfile(id.value); Object.assign(form, { name: project.name, topic: project.topic, direction: project.direction, references: project.references }) } const local = uni.getStorageSync(storageKey()); if (local) Object.assign(form, local); ready.value = true } catch (e) { error.value = errorMessage(e) } finally { busy.value = false } })
function addReference() { if (!busy.value && !uploading.value && form.references.length < 50) form.references.push({ title: '', authors: '', year: '', url: '', notes: '' }) }
async function uploadPDF() {
  if (busy.value || uploading.value || form.references.length >= 50) return
  uploading.value = true; error.value = ''
  try {
    const reference = await api.uploadReference()
    if (form.references.some(item => item.document?.sha256 === reference.document.sha256)) { error.value = '这份 PDF 已添加，无需重复上传'; return }
    form.references.push(reference); toast('正文已提取，保存课题后即可用于对话')
  } catch (e) { if (!e.cancelled) { error.value = errorMessage(e); uni.showModal({ title: 'PDF 未能添加', content: error.value, showCancel: false }) } }
  finally { uploading.value = false }
}
async function viewPDF(reference) {
  if (openingPdf.value) return
  openingPdf.value = true
  try { await api.openReference(reference.document_id) }
  catch (e) { uni.showModal({ title: '暂时无法打开 PDF', content: errorMessage(e), showCancel: false }) }
  finally { openingPdf.value = false }
}
async function removeReference(index) { if (busy.value || uploading.value) return; if (!form.references[index].title || await confirmAction('移除这篇参考文献？', '保存课题资料后移除该文献及 PDF。此前的对话和汇报会保留。')) form.references.splice(index, 1) }
async function create() {
  if (busy.value || uploading.value) return
  if (![form.name, form.topic, form.direction].every(value => value.trim())) { error.value = '请填写课题名称、研究主题和具体方向'; return }
  if (form.references.some(reference => !reference.title.trim())) { error.value = '请填写每篇文献的标题，或移除空白文献'; return }
  busy.value = true; error.value = ''
  try { const result = await api.saveProject(id.value, JSON.parse(JSON.stringify(form))); ready.value = false; uni.removeStorageSync(storageKey()); toast(id.value ? '课题资料已保存' : '课题已创建'); if (id.value) uni.navigateBack(); else uni.redirectTo({ url: '/pages/chat/index?id=' + result.project_id }) }
  catch (e) { error.value = errorMessage(e) } finally { busy.value = false }
}
</script>
<style scoped>.direction{height:260rpx}.reference{border-top:1rpx solid #edf0f5;margin-top:22rpx;padding-top:10rpx}.reference-row{display:flex;gap:14rpx}.reference-row input:first-child{flex:2}.reference-row input:last-child{flex:1}.upload-help{font-size:23rpx}.pdf-info{background:#f1f5ff;padding:20rpx;border-radius:14rpx;font-size:24rpx;line-height:1.7}.pdf-name{font-weight:600;word-break:break-all}.pdf-info button{margin:16rpx 0;text-align:center}</style>
