<template>
  <!-- 空状态 / 错误态：图标 + 一句人话 + 可选主按钮 -->
  <div class="empty-state">
    <el-icon :size="44" class="empty-icon">
      <component :is="error ? WarningFilled : Box" />
    </el-icon>
    <div class="empty-title">{{ title }}</div>
    <div class="empty-desc">{{ desc }}</div>
    <el-button v-if="actionText" :type="error ? 'warning' : 'primary'" plain size="small" @click="$emit('action')">
      {{ actionText }}
    </el-button>
  </div>
</template>

<script setup lang="ts">
import { Box, WarningFilled } from '@element-plus/icons-vue'

withDefaults(defineProps<{
  title: string
  desc?: string
  actionText?: string
  error?: boolean   // 错误态样式
}>(), { desc: '', actionText: '', error: false })

defineEmits<{ (e: 'action'): void }>()
</script>

<style scoped>
.empty-state {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 48px 24px; text-align: center;
}
.empty-icon { color: var(--text-disabled); }
.empty-title { font-size: 15px; color: var(--text-primary); font-weight: 600; }
.empty-desc { font-size: 13px; color: var(--text-secondary); max-width: 320px; }
</style>
