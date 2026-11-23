<template><view class="preview"><view v-for="(line, index) in lines" :key="index" :class="line.type">{{ line.text || ' ' }}</view></view></template>
<script setup>
import { computed } from 'vue'
const props = defineProps({ content: { type: String, default: '' } })
const lines = computed(() => props.content.split('\n').map(line => {
  if (line.startsWith('# ')) return { type: 'heading', text: line.slice(2) }
  if (line.startsWith('## ')) return { type: 'section', text: line.slice(3) }
  if (line.startsWith('- ')) return { type: 'bullet', text: '• ' + line.slice(2) }
  return { type: 'paragraph', text: line }
}))
</script>
<style scoped>.preview{white-space:pre-wrap;word-break:break-word;line-height:1.85}.heading{font-size:36rpx;font-weight:700;margin:12rpx 0}.section{font-size:29rpx;font-weight:700;color:#315bc6;margin:20rpx 0 8rpx}.paragraph{font-size:26rpx;min-height:12rpx}.bullet{font-size:26rpx;margin:10rpx 0}</style>
