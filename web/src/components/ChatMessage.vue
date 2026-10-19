<template>
  <div class="msg-row" :class="msg.role">
    <!-- 助手头像 -->
    <div v-if="msg.role === 'assistant'" class="avatar assistant">AI</div>

    <div class="msg-body" :class="{ clickable: msg.resp?.results?.length, active }" @click="onSelect">
      <!-- 生成中占位 -->
      <div v-if="msg.loading" class="loading-line">
        <el-icon class="is-loading"><Loading /></el-icon>
        值班助手正在协同<span class="dots"><i>.</i><i>.</i><i>.</i></span>
      </div>

      <template v-else>
        <!-- 正文：Markdown 渲染 + 实体高亮（井号/指标可点击跳转） -->
        <div
          class="md-body"
          :class="{ stopped: msg.stopped }"
          @click="onEntityClick"
          v-html="rendered"
        />

        <template v-if="msg.resp">
          <!-- 元信息行：置信度 + 引用来源 -->
          <div class="meta-line">
            <ConfidenceTag :level="msg.resp.confidence_level" :basis="confidenceBasis" />
            <el-popover
              v-for="(c, i) in msg.resp.citations" :key="i"
              trigger="click" placement="top" width="320"
            >
              <template #reference>
                <span class="cite-chip" @click.stop>[{{ c }}]</span>
              </template>
              <div class="cite-pop">
                <div class="cite-title">{{ c }}</div>
                <div class="cite-text">{{ citeSnippet(c) }}</div>
                <el-button size="small" text type="primary" @click.stop="goSource(c)">查看来源</el-button>
              </div>
            </el-popover>
          </div>

          <!-- 澄清选项：点一下即作为回复发送 -->
          <div v-if="msg.resp.need_clarify && msg.resp.clarify_options.length" class="clarify-group">
            <button
              v-for="opt in msg.resp.clarify_options" :key="opt"
              class="clarify-chip"
              @click.stop="$emit('send', opt)"
            >{{ opt }}</button>
          </div>

          <!-- 工具栏：复制 / 重新生成 / 反馈 -->
          <div class="toolbar">
            <el-tooltip content="复制" placement="top">
              <button class="tool-btn" @click.stop="copy"><el-icon><CopyDocument /></el-icon></button>
            </el-tooltip>
            <el-tooltip content="重新生成" placement="top">
              <button class="tool-btn" @click.stop="$emit('regenerate')"><el-icon><RefreshRight /></el-icon></button>
            </el-tooltip>
            <el-tooltip content="回答有帮助" placement="top">
              <button class="tool-btn" :class="{ voted: vote === 1 }" @click.stop="feedback(1)"><el-icon><CircleCheck /></el-icon></button>
            </el-tooltip>
            <el-tooltip content="回答有问题（沉淀为知识候选）" placement="top">
              <button class="tool-btn" :class="{ voted: vote === -1 }" @click.stop="feedback(-1)"><el-icon><CircleClose /></el-icon></button>
            </el-tooltip>
            <span class="trace-hint mono" v-if="msg.resp.trace_id">{{ msg.resp.trace_id }}</span>
          </div>
        </template>
      </template>
    </div>

    <!-- 用户头像 -->
    <div v-if="msg.role === 'user'" class="avatar user">值</div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import { CircleCheck, CircleClose, CopyDocument, Loading, RefreshRight } from '@element-plus/icons-vue'
import ConfidenceTag from './ConfidenceTag.vue'
import type { ChatMsg } from '@/types/chat'
import { METRICS, KB_DOCS } from '@/api/mock/data'

const props = defineProps<{ msg: ChatMsg; active?: boolean }>()
const emit = defineEmits<{
  (e: 'send', text: string): void
  (e: 'regenerate'): void
  (e: 'select', msg: ChatMsg): void
}>()

const router = useRouter()
const vote = ref(0)

marked.setOptions({ breaks: true })

/* ---------- 实体高亮：井号 / 指标名 → 可点击点状下划线 ---------- */
// 指标实体表（点表全集 + 常用口语指标）
const METRIC_NAMES = [...new Set([...METRICS.map(m => m.metric), '回压', '含水率', '产量'])]
const WELL_RE = /W-\d+/g

/** 只在文本节点内做替换，避免破坏 HTML 标签与已有链接 */
function injectEntities(html: string): string {
  return html.split(/(<[^>]+>)/).map(seg => {
    if (seg.startsWith('<')) return seg // 标签原样保留
    let out = seg.replace(WELL_RE, m => `<span class="entity entity-well" data-well="${m}">${m}</span>`)
    for (const name of METRIC_NAMES) {
      if (!out.includes(name)) continue
      out = out.split(name).join(`<span class="entity entity-metric" data-metric="${name}">${name}</span>`)
    }
    return out
  }).join('')
}

const rendered = computed(() => {
  if (!props.msg.content) return ''
  return injectEntities(marked.parse(props.msg.content) as string)
})

/** 实体点击跳转生产数据页（路由带 query 自动定位曲线） */
function onEntityClick(e: MouseEvent) {
  const el = (e.target as HTMLElement).closest('.entity') as HTMLElement | null
  if (!el) return
  const well = el.dataset.well
  const metric = el.dataset.metric
  router.push({ path: '/production', query: { ...(well ? { well } : {}), ...(metric ? { metric } : {}) } })
}

/* ---------- 引用来源 ---------- */
function matchDoc(c: string) {
  // 依次尝试 doc_id / 标题 / 来源编号 三种口径匹配到具体文档
  return KB_DOCS.find(d => c.includes(d.doc_id))
    ?? KB_DOCS.find(d => c.includes(d.title))
    ?? KB_DOCS.find(d => c.includes(d.source_ref))
    ?? null
}
/** 匹配指标类引用：如 "W3.wellhead_pressure"、"W3.wellhead_pressure 超阈值" */
function matchMetric(c: string): { well: string; metric: string } | null {
  const m = c.match(/W(\d+)\.([a-z_]+)/i)
  if (!m) return null
  const well = `W-${m[1]}`
  const suffix = m[2]
  const def = METRICS.find(x => x.suffix === suffix)
  return def ? { well, metric: def.metric } : null
}
function citeSnippet(c: string): string {
  const mm = matchMetric(c)
  if (mm) return `时序指标：${mm.well} · ${mm.metric}（跳生产数据页查看曲线）`
  const doc = matchDoc(c)
  return doc ? doc.summary : '来源片段：' + c
}
function goSource(c: string) {
  // ① 指标类引用 → 生产数据页定位该井该指标曲线
  const mm = matchMetric(c)
  if (mm) { router.push({ path: '/production', query: { well: mm.well, metric: mm.metric } }); return }
  // ② 文档类引用 → 知识库文档库并直接打开该文档
  const doc = matchDoc(c)
  router.push({ path: '/knowledge', query: { tab: 'docs', ...(doc ? { doc: doc.doc_id } : {}) } })
}

/* ---------- 置信度依据 ---------- */
const confidenceBasis = computed(() => {
  const rs = props.msg.resp?.results ?? []
  if (!rs.length) return '无 Agent 证据，回答仅供参考'
  const avg = rs.reduce((s, r) => s + r.confidence, 0) / rs.length
  return `综合 ${rs.length} 个 Agent，平均置信度 ${(avg * 100).toFixed(0)}%`
})

/* ---------- 工具栏动作 ---------- */
async function copy() {
  await navigator.clipboard.writeText(props.msg.content)
  ElMessage.success('已复制到剪贴板')
}
function feedback(v: number) {
  vote.value = vote.value === v ? 0 : v
  if (vote.value === -1) ElMessage.warning('已反馈：该回答将加入知识候选，待运营修正')
  else if (vote.value === 1) ElMessage.success('感谢反馈')
}
function onSelect() { if (props.msg.resp?.results?.length) emit('select', props.msg) }
</script>

<style scoped>
.msg-row { display: flex; gap: 10px; margin-bottom: 18px; }
.msg-row.user { flex-direction: row-reverse; }

.avatar {
  width: 30px; height: 30px; border-radius: 50%; flex: none;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 600;
}
.avatar.assistant { background: var(--accent-dim); color: var(--accent-hover); border: 1px solid var(--accent); }
.avatar.user { background: var(--bg-elevated); color: var(--text-secondary); border: 1px solid var(--border-strong); }

.msg-body {
  max-width: calc(100% - 60px);
  padding: 10px 14px;
  border-radius: var(--radius-card);
  border: 1px solid transparent;
  transition: border-color .15s ease-out;
}
.msg-row.assistant .msg-body { background: var(--bg-panel); border-color: var(--border); }
.msg-row.user .msg-body { background: var(--accent-dim); border-color: rgba(47,129,247,.35); }
.msg-body.active { border-color: var(--accent) !important; box-shadow: 0 0 0 1px var(--accent); }

.loading-line { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); }
.dots i { animation: blink 1.2s infinite; font-style: normal; }
.dots i:nth-child(2) { animation-delay: .2s; }
.dots i:nth-child(3) { animation-delay: .4s; }
@keyframes blink { 0%, 100% { opacity: .2 } 50% { opacity: 1 } }

.md-body { font-size: 14px; line-height: 1.7; word-break: break-word; }
.md-body.stopped { opacity: .6; }
.md-body :deep(p) { margin: 0 0 8px; }
.md-body :deep(p:last-child) { margin-bottom: 0; }
.md-body :deep(ol), .md-body :deep(ul) { margin: 4px 0 8px; padding-left: 22px; }
.md-body :deep(strong) { color: var(--accent-hover); font-weight: 600; }
.md-body :deep(code) {
  font-family: var(--font-mono); font-size: 12.5px;
  background: var(--bg-elevated); padding: 1px 5px; border-radius: 4px;
}
.md-body :deep(pre) {
  background: var(--bg-input); border: 1px solid var(--border);
  padding: 10px 12px; border-radius: var(--radius-btn); overflow-x: auto;
}
.md-body :deep(table) { border-collapse: collapse; margin: 8px 0; }
.md-body :deep(th), .md-body :deep(td) { border: 1px solid var(--border); padding: 4px 10px; font-size: 13px; }
.md-body :deep(th) { background: var(--bg-elevated); }

/* 实体：点状下划线可点击 */
.md-body :deep(.entity) {
  border-bottom: 1px dotted var(--accent-hover);
  color: var(--accent-hover); cursor: pointer;
  font-family: var(--font-mono); font-size: 13.5px;
}
.md-body :deep(.entity:hover) { background: var(--accent-dim); border-radius: 3px; }

.meta-line { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.cite-chip {
  font-size: 11px; color: var(--text-secondary);
  background: var(--bg-elevated); border: 1px solid var(--border);
  padding: 1px 8px; border-radius: 10px; cursor: pointer; line-height: 18px;
}
.cite-chip:hover { color: var(--accent-hover); border-color: var(--accent); }
.cite-pop .cite-title { font-weight: 600; margin-bottom: 6px; }
.cite-pop .cite-text { color: var(--text-secondary); font-size: 12.5px; line-height: 1.6; margin-bottom: 8px; }

.clarify-group { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.clarify-chip {
  border: 1px solid var(--accent); color: var(--accent-hover);
  background: var(--accent-dim); border-radius: 16px;
  padding: 4px 14px; font-size: 13px; cursor: pointer;
  transition: background .15s ease-out;
}
.clarify-chip:hover { background: rgba(47,129,247,.28); }

.toolbar { display: flex; align-items: center; gap: 2px; margin-top: 8px; opacity: .75; }
.tool-btn {
  min-width: 28px; min-height: 28px; border: none; background: transparent;
  color: var(--text-secondary); border-radius: var(--radius-btn); cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; font-size: 14px;
}
.tool-btn:hover { background: var(--bg-elevated); color: var(--text-primary); }
.tool-btn.voted { color: var(--accent-hover); }
.trace-hint { margin-left: auto; font-size: 11px; color: var(--text-disabled); }
</style>
