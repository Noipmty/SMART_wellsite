<template>
  <!-- 告警列表卡片：左等级色竖条 + 井号 + 摘要 + hit 徽标 + 抑制计数 -->
  <div
    class="alarm-card" :class="[`lv-${alert.level}`, { selected, overtime: alert.overtime }]"
    @click="$emit('select', alert)"
  >
    <span class="lv-bar" />
    <el-checkbox
      class="card-check" :model-value="checked"
      @click.stop @change="$emit('check', alert)"
    />
    <div class="card-main">
      <div class="card-top">
        <span class="well mono">{{ alert.scope }}</span>
        <LevelTag :level="alert.level" size="small" />
        <span v-if="alert.overtime" class="overtime-tag">超时</span>
        <span class="time mono">{{ fmtShort(alert.last_seen) }}</span>
      </div>
      <div class="card-title">{{ alert.cause }}</div>
      <div class="card-bottom">
        <span class="hit-badge mono">hit {{ alert.hit_count }}</span>
        <span v-if="alert.suppressed_count" class="suppressed mono">抑制 {{ alert.suppressed_count }}</span>
        <span class="status-text" :class="alert.status">{{ STATUS_CN[alert.status] }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import LevelTag from './LevelTag.vue'
import type { Alert } from '@/api/types'
import { fmtShort } from '@/utils/format'

defineProps<{ alert: Alert; selected?: boolean; checked?: boolean }>()
defineEmits<{ (e: 'select', a: Alert): void; (e: 'check', a: Alert): void }>()

const STATUS_CN = { active: '活动', acknowledged: '已确认', resolved: '已解决' } as const
</script>

<style scoped>
.alarm-card {
  position: relative;
  display: flex; align-items: flex-start; gap: 8px;
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  padding: 10px 12px 10px 16px;
  cursor: pointer;
  transition: background .15s ease-out, border-color .15s ease-out;
}
.alarm-card:hover { background: var(--bg-elevated); }
.alarm-card.selected { border-color: var(--accent); background: var(--bg-elevated); box-shadow: 0 0 0 1px var(--accent); }

/* 左侧等级色竖条 */
.lv-bar {
  position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  border-radius: var(--radius-card) 0 0 var(--radius-card);
}
.lv-紧急 > .lv-bar { background: var(--level-critical); }
.lv-预警 > .lv-bar { background: var(--level-warning); }
.lv-提醒 > .lv-bar { background: var(--level-info); }
.lv-提示 > .lv-bar { background: var(--level-watch); }

/* 超时：整条红脉冲 + 红边（全局 .alarm-overtime 动画，此处叠加左边条加粗） */
.alarm-card.overtime { animation: alarm-pulse 2s ease-in-out infinite; border-color: var(--level-critical); }
.alarm-card.overtime .lv-bar { width: 6px; }

.card-check { margin-top: 2px; flex: none; height: auto; }

.card-main { flex: 1; min-width: 0; }
.card-top { display: flex; align-items: center; gap: 8px; }
.well { font-weight: 700; font-size: 14px; color: var(--text-primary); }
.overtime-tag {
  font-size: 11px; font-weight: 600; color: #fff;
  background: var(--level-critical); border-radius: var(--radius-tag);
  padding: 0 6px; line-height: 18px;
}
.time { margin-left: auto; font-size: 11.5px; color: var(--text-disabled); }

.card-title {
  font-size: 13px; color: var(--text-primary); margin-top: 3px;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}

.card-bottom { display: flex; align-items: center; gap: 8px; margin-top: 5px; font-size: 11.5px; }
.hit-badge {
  color: var(--accent-hover); background: var(--accent-dim);
  border: 1px solid rgba(47,129,247,.35); border-radius: var(--radius-tag);
  padding: 0 6px; line-height: 17px;
}
.suppressed { color: var(--text-disabled); }
.status-text { margin-left: auto; }
.status-text.active { color: var(--level-critical); }
.status-text.acknowledged { color: var(--level-warning); }
.status-text.resolved { color: var(--level-ok); }
</style>
