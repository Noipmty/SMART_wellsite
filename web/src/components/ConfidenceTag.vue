<template>
  <!-- 置信度胶囊：高=绿 / 中=橙 / 低=红，hover 显示依据说明 -->
  <el-tooltip :content="basis || defaultBasis" placement="top" :disabled="!level">
    <span v-if="level" class="conf-tag" :class="`conf-${level}`">
      <span class="conf-dot" />置信度 {{ level }}
    </span>
  </el-tooltip>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ConfidenceLevel } from '@/api/types'

const props = defineProps<{ level: ConfidenceLevel | null; basis?: string }>()

const defaultBasis = computed(() =>
  props.level === '高' ? '多源数据一致，证据链完整'
    : props.level === '中' ? '主要证据成立，部分数据待补充'
      : '证据不足或存在冲突，请人工复核',
)
</script>

<style scoped>
.conf-tag {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 1px 8px; border-radius: 10px;
  font-size: 11px; line-height: 18px; cursor: default;
  border: 1px solid transparent;
}
.conf-dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.conf-高 { color: var(--level-ok);       background: rgba(63, 185, 80, .1);  border-color: rgba(63, 185, 80, .35); }
.conf-中 { color: var(--level-warning);  background: rgba(210, 153, 34, .1); border-color: rgba(210, 153, 34, .35); }
.conf-低 { color: var(--level-critical); background: rgba(248, 81, 73, .1);  border-color: rgba(248, 81, 73, .35); }
</style>
