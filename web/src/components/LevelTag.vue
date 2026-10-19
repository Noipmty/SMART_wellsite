<template>
  <!-- 等级胶囊：图标 + 文字 + 等级色（色盲友好，不只靠颜色区分） -->
  <span class="level-tag" :class="[`lv-${level}`, size]">
    <el-icon :size="size === 'small' ? 12 : 14"><component :is="icon" /></el-icon>
    <span>{{ level }}</span>
  </span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { BellFilled, CircleCloseFilled, InfoFilled, WarningFilled } from '@element-plus/icons-vue'
import type { Level } from '@/api/types'

const props = withDefaults(defineProps<{ level: Level; size?: 'small' | 'default' }>(), { size: 'default' })

// 四档等级各配一个辨识度图标
const ICONS = { 提示: InfoFilled, 提醒: BellFilled, 预警: WarningFilled, 紧急: CircleCloseFilled } as const
const icon = computed(() => ICONS[props.level])
</script>

<style scoped>
.level-tag {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 1px 8px; border-radius: var(--radius-tag);
  font-size: 12px; font-weight: 600; line-height: 20px;
  border: 1px solid transparent; white-space: nowrap;
}
.level-tag.small { padding: 0 6px; font-size: 11px; line-height: 18px; }
/* 色 = 12% 底 + 实色文字与边框，暗底下保证对比度 */
.lv-紧急 { color: var(--level-critical); background: rgba(248, 81, 73, .12); border-color: rgba(248, 81, 73, .4); }
.lv-预警 { color: var(--level-warning); background: rgba(210, 153, 34, .12); border-color: rgba(210, 153, 34, .4); }
.lv-提醒 { color: var(--level-info);    background: rgba(88, 166, 255, .12); border-color: rgba(88, 166, 255, .4); }
.lv-提示 { color: var(--level-watch);    background: rgba(188, 140, 255, .12); border-color: rgba(188, 140, 255, .4); }
</style>
