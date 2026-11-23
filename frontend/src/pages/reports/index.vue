<template><view class="page"><view class="title">从日常对话，到组会汇报</view><view class="muted">先选择课题，再选择起止日期。汇报仅依据该课题在这段时间里的用户发言。</view><view v-if="error" class="card error">{{ error }}<button @tap="load">重试</button></view><view v-for="project in projects" :key="project.id" class="card project"><view class="between"><view class="subtitle">{{ project.name }}</view><text v-if="project.status === 'active'" class="tag">当前</text></view><view class="muted">{{ project.topic }}</view><button class="primary" @tap="open(project.id)">选择日期 / 查看历史汇报</button></view><view v-if="!projects.length" class="card empty"><view class="muted">先创建课题，和 AI 聊聊今天做了什么。</view><button @tap="create">创建课题</button></view></view></template>
<script setup>
import { ref } from 'vue'
import { onShow } from '@dcloudio/uni-app'
import { api, errorMessage } from '../../utils/api'
const projects = ref([]), error = ref('')
async function load() { error.value = ''; try { projects.value = await api.researchProjects() } catch (e) { error.value = errorMessage(e) } }
function open(id) { uni.navigateTo({ url: '/pages/report/index?id=' + id }) }
function create() { uni.navigateTo({ url: '/pages/onboarding/index' }) }
onShow(load)
</script>
<style scoped>.project{margin-top:26rpx}.project .subtitle{max-width:80%}</style>
