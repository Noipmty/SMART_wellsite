<template>
  <!-- 协同过程面板：本次 trace 的 Agent 链路时间线（差异化卖点） -->
  <div class="agent-timeline">
    <div class="tl-header">
      <span class="tl-title">协同过程</span>
      <span v-if="running" class="tl-status running">编排中…</span>
      <span v-else-if="results.length" class="tl-status done">已完成</span>
    </div>

    <!-- 空态 -->
    <div v-if="!running && !results.length" class="tl-empty">
      <el-icon :size="30"><Connection /></el-icon>
      <p>发送一条问题后，这里会展示<br>数据采控 → 诊断 → 告警 的协同链路</p>
    </div>

    <div v-else class="tl-body">
      <div
        v-for="node in nodes" :key="node.key"
        class="tl-node" :class="[node.status, { expanded: expanded.has(node.key) }]"
      >
        <div class="node-head" @click="toggle(node.key)">
          <span class="node-line" />
          <span class="node-icon" :class="node.status">
            <el-icon v-if="node.status === 'running'" class="is-loading"><Loading /></el-icon>
            <el-icon v-else-if="node.status === 'success'"><CircleCheckFilled /></el-icon>
            <el-icon v-else-if="node.status === 'failed'"><CircleCloseFilled /></el-icon>
            <el-icon v-else><Clock /></el-icon>
          </span>
          <div class="node-main">
            <div class="node-name">
              {{ node.name }}
              <span class="node-ms mono" v-if="node.ms != null">{{ node.ms }}ms</span>
            </div>
            <div class="node-conclusion" v-if="node.conclusion">{{ node.conclusion }}</div>
          </div>
          <el-icon v-if="node.result" class="node-caret" :class="{ open: expanded.has(node.key) }"><ArrowDown /></el-icon>
        </div>

        <!-- 展开：证据 / 参数建议 / 原始 JSON -->
        <div v-if="expanded.has(node.key) && node.result" class="node-detail">
          <div v-if="node.result.evidence.length" class="detail-block">
            <div class="detail-label">证据 evidence</div>
            <div class="kv-list">
              <div v-for="(ev, i) in node.result.evidence" :key="i" class="kv-item">
                <span class="kv-key">{{ ev.metric }}</span>
                <span class="kv-val mono">{{ ev.value ?? '—' }}</span>
                <span v-if="ev.trend" class="kv-trend" :class="trendCls(ev.trend)">{{ ev.trend }}</span>
              </div>
            </div>
          </div>

          <div v-if="node.result.suggestion" class="detail-block">
            <div class="detail-label">建议 suggestion</div>
            <div class="suggestion-text">{{ node.result.suggestion }}</div>
          </div>

          <div v-for="(pa, i) in node.result.parameter_advice" :key="'pa' + i" class="param-card">
            <div class="param-head">
              <span class="mono param-name">{{ pa.param }}</span>
              <span class="mono param-change">{{ pa.from }} → {{ pa.to }}</span>
            </div>
            <div class="param-reason">{{ pa.reason }}<template v-if="pa.observe_hours">（观察 {{ pa.observe_hours }}h）</template></div>
            <el-button size="small" type="primary" plain @click="applyAdvice(pa.param)">应用到工单</el-button>
          </div>

          <details class="raw-json">
            <summary>原始数据 raw</summary>
            <pre>{{ JSON.stringify(node.result, null, 2) }}</pre>
          </details>
        </div>
      </div>
    </div>

    <!-- 底部：trace 信息 -->
    <div v-if="results.length" class="tl-footer">
      <span class="trace-id mono clickable" title="点击复制" @click="copyTrace">{{ traceId }}</span>
      <span class="total-ms mono">总耗时 {{ totalMs }}ms</span>
      <span class="full-link" @click="ElMessage.info('完整链路页在真实环境对接 tracing 服务')">查看完整链路 →</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, CircleCheckFilled, CircleCloseFilled, Clock, Connection, Loading } from '@element-plus/icons-vue'
import type { AgentResultView } from '@/api/types'
import { agentCn } from '@/api/mock/engine'

const props = withDefaults(defineProps<{
  results?: AgentResultView[]
  traceId?: string
  running?: boolean
  /** 生成中时展示的占位链路（中文名列表） */
  pendingAgents?: string[]
}>(), { results: () => [], traceId: '', running: false, pendingAgents: () => ['数据采控', '诊断分析', '告警处置'] })

interface TlNode {
  key: string
  name: string
  ms: number | null
  status: 'pending' | 'running' | 'success' | 'failed'
  conclusion: string
  result?: AgentResultView
}

/** 生成中 → 占位节点（第一个 running，其余 pending）；完成后 → 真实结果 */
const nodes = computed<TlNode[]>(() => {
  if (props.results.length) {
    return props.results.map(r => ({
      key: r.agent, name: agentCn(r.agent), ms: r.elapsed_ms,
      status: r.error ? 'failed' : 'success', conclusion: r.conclusion, result: r,
    }))
  }
  if (props.running) {
    return props.pendingAgents.map((name, i) => ({
      key: name, name, ms: null, status: i === 0 ? 'running' : 'pending', conclusion: '',
    }))
  }
  return []
})

/* 默认展开第一个节点 */
const expanded = ref<Set<string>>(new Set())
watch(nodes, ns => { if (ns.length && !expanded.value.size) expanded.value = new Set([ns[0].key]) }, { immediate: true })

function toggle(key: string) {
  const s = new Set(expanded.value)
  s.has(key) ? s.delete(key) : s.add(key)
  expanded.value = s
}

function trendCls(t: string) {
  return t.includes('升') || t.includes('上升') ? 'up' : t.includes('降') || t.includes('下降') ? 'down' : ''
}

const totalMs = computed(() => props.results.reduce((s, r) => s + (r.elapsed_ms ?? 0), 0))

async function copyTrace() {
  if (!props.traceId) return
  await navigator.clipboard.writeText(props.traceId)
  ElMessage.success('trace_id 已复制')
}

function applyAdvice(param: string) {
  ElMessage.success(`参数建议「${param}」已写入关联工单，待现场确认`)
}
</script>

<style scoped>
.agent-timeline { display: flex; flex-direction: column; height: 100%; min-height: 0; }

.tl-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 14px; border-bottom: 1px solid var(--border); flex: none;
}
.tl-title { font-weight: 600; font-size: 14px; }
.tl-status { font-size: 12px; }
.tl-status.running { color: var(--accent-hover); }
.tl-status.done { color: var(--level-ok); }

.tl-empty {
  flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px; color: var(--text-disabled); text-align: center; font-size: 13px; line-height: 1.7;
}

.tl-body { flex: 1; overflow-y: auto; padding: 12px 14px; }

.tl-node { position: relative; padding-bottom: 14px; }
.node-head { display: flex; align-items: flex-start; gap: 10px; cursor: pointer; }

/* 垂直连接线 */
.node-line { position: absolute; left: 9px; top: 24px; bottom: 0; width: 2px; background: var(--border); }
.tl-node:last-child .node-line { display: none; }

.node-icon {
  width: 20px; height: 20px; flex: none; z-index: 1;
  display: inline-flex; align-items: center; justify-content: center;
  border-radius: 50%; font-size: 13px; background: var(--bg-panel);
}
.node-icon.success { color: var(--level-ok); }
.node-icon.failed { color: var(--level-critical); }
.node-icon.running { color: var(--accent-hover); }
.node-icon.pending { color: var(--text-disabled); }

.tl-node.running .node-icon { animation: agent-running 1.1s ease-out infinite; }

.node-main { flex: 1; min-width: 0; }
.node-name { font-size: 13.5px; font-weight: 600; display: flex; align-items: center; gap: 8px; }
.node-ms { font-size: 11px; color: var(--text-disabled); font-weight: 400; }
.node-conclusion {
  font-size: 12.5px; color: var(--text-secondary); line-height: 1.55; margin-top: 2px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.tl-node.expanded .node-conclusion { -webkit-line-clamp: unset; }

.node-caret { color: var(--text-disabled); font-size: 12px; margin-top: 4px; transition: transform .15s ease-out; }
.node-caret.open { transform: rotate(180deg); }

.node-detail { margin: 8px 0 0 30px; display: flex; flex-direction: column; gap: 10px; }
.detail-label { font-size: 11px; color: var(--text-disabled); margin-bottom: 4px; font-family: var(--font-mono); }

.kv-list { border: 1px solid var(--border); border-radius: var(--radius-btn); overflow: hidden; }
.kv-item {
  display: flex; align-items: center; gap: 8px;
  padding: 4px 10px; font-size: 12.5px;
  background: var(--bg-input);
}
.kv-item + .kv-item { border-top: 1px solid var(--border); }
.kv-key { color: var(--text-secondary); min-width: 64px; }
.kv-val { color: var(--text-primary); }
.kv-trend { margin-left: auto; font-size: 11px; }
.kv-trend.up { color: var(--level-critical); }
.kv-trend.down { color: var(--level-warning); }

.suggestion-text { font-size: 12.5px; color: var(--text-primary); background: var(--accent-dim); border-radius: var(--radius-btn); padding: 6px 10px; }

.param-card {
  border: 1px solid var(--accent); border-radius: var(--radius-btn);
  background: var(--accent-dim); padding: 8px 10px;
  display: flex; flex-direction: column; gap: 6px; align-items: flex-start;
}
.param-head { display: flex; gap: 10px; font-size: 13px; }
.param-name { color: var(--accent-hover); font-weight: 600; }
.param-change { color: var(--text-primary); }
.param-reason { font-size: 12px; color: var(--text-secondary); }

.raw-json summary { font-size: 11px; color: var(--text-disabled); cursor: pointer; font-family: var(--font-mono); }
.raw-json pre {
  margin: 6px 0 0; padding: 8px 10px; font-size: 11px; line-height: 1.5;
  background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius-btn);
  max-height: 200px; overflow: auto; color: var(--text-secondary);
}

.tl-footer {
  flex: none; display: flex; align-items: center; gap: 10px;
  padding: 10px 14px; border-top: 1px solid var(--border); font-size: 11px;
}
.trace-id { color: var(--text-secondary); border-radius: 4px; padding: 1px 4px; }
.total-ms { color: var(--text-disabled); }
.full-link { margin-left: auto; color: var(--accent-hover); cursor: pointer; }
</style>
