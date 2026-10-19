<template>
  <div class="knowledge-view">
    <!-- ============ 顶部 Tab：候选队列默认（自进化心证页面） ============ -->
    <el-tabs v-model="tab" class="kb-tabs">
      <el-tab-pane label="候选队列" name="candidates" />
      <el-tab-pane label="文档库" name="docs" />
      <el-tab-pane label="检索测试" name="search" />
    </el-tabs>

    <!-- ============ 候选队列 ============ -->
    <div v-show="tab === 'candidates'" class="tab-body">
      <div class="cand-toolbar">
        <el-select v-model="sourceFilter" placeholder="来源" clearable style="width: 130px">
          <el-option label="工单沉淀" value="workorder" />
          <el-option label="告警沉淀" value="alert_dedup" />
          <el-option label="对话沉淀" value="trace" />
        </el-select>
        <span class="mono hint">{{ filteredCandidates.length }} 条待审核</span>
        <div class="spacer" />
        <template v-if="checkedIds.size">
          <span class="mono hint">已选 {{ checkedIds.size }}</span>
          <el-button size="small" type="primary" plain :loading="acting" @click="batchApprove">批量采纳</el-button>
          <el-button size="small" type="danger" plain :loading="acting" @click="batchReject">批量驳回</el-button>
        </template>
      </div>

      <div class="cand-scroll">
        <EmptyState
          v-if="!filteredCandidates.length"
          title="候选队列为空"
          desc="关闭工单或对话负反馈会自动沉淀到这里"
        />
        <div v-for="c in filteredCandidates" :key="c.candidate_id" class="cand-card panel-card">
          <div class="cand-head">
            <el-checkbox
              :model-value="checkedIds.has(c.candidate_id)"
              @change="toggleCheck(c.candidate_id)"
            />
            <span class="source-badge" :class="c.source_type">{{ SOURCE_CN[c.source_type] }}</span>
            <span class="cand-title">{{ c.title }}</span>
            <span class="mono cand-time">{{ fmtAgo(c.created_at) }}</span>
          </div>

          <!-- 内联编辑态（采纳前可修订） -->
          <template v-if="editingId === c.candidate_id">
            <el-input v-model="editForm.title" class="edit-field" placeholder="标题" />
            <el-input v-model="editForm.text" type="textarea" :rows="4" class="edit-field" placeholder="正文" />
            <el-select
              v-model="editForm.tags" multiple filterable allow-create default-first-option
              class="edit-field" placeholder="标签（回车创建）"
            >
              <el-option v-for="t in c.tags" :key="t" :label="t" :value="t" />
            </el-select>
          </template>
          <template v-else>
            <div class="cand-text">{{ c.text }}</div>
            <div class="cand-meta mono">
              {{ c.source_ref }} · {{ c.doc_type }} · {{ c.tags.join(' / ') }}
            </div>
          </template>

          <div class="cand-actions">
            <template v-if="editingId === c.candidate_id">
              <el-button size="small" type="primary" :loading="acting" @click="doApprove(c)">确认采纳</el-button>
              <el-button size="small" @click="editingId = ''">取消</el-button>
            </template>
            <template v-else>
              <el-button size="small" type="primary" plain @click="startEdit(c)">采纳</el-button>
              <el-button size="small" type="danger" plain @click="openReject(c)">驳回</el-button>
            </template>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 文档库 ============ -->
    <div v-show="tab === 'docs'" class="tab-body">
      <div class="docs-toolbar">
        <span class="mono docs-count">{{ docs.length }} 篇文档</span>
        <el-button type="primary" size="small" @click="addDialog = true">+ 添加文档</el-button>
      </div>
      <el-table
        ref="docTableRef" :data="docs" class="doc-table"
        :header-cell-style="{ background: 'var(--bg-elevated)' }"
        :row-class-name="docRowClass"
        @row-click="openDocView"
      >
        <el-table-column prop="title" label="标题" min-width="240" show-overflow-tooltip />
        <el-table-column prop="doc_type" label="类型" width="80" />
        <el-table-column label="索引状态" width="100">
          <template #default="{ row }">
            <el-tag :type="INDEX_TAG[row.status as IndexStatus]" size="small" effect="dark">
              {{ INDEX_CN[row.status as IndexStatus] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="chunk_count" label="分块" width="70" align="right" />
        <el-table-column label="标签" min-width="160">
          <template #default="{ row }">
            <el-tag v-for="t in row.tags" :key="t" size="small" effect="plain" style="margin-right:4px">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="source_ref" label="来源" width="170" show-overflow-tooltip />
        <el-table-column label="更新" width="100">
          <template #default="{ row }"><span class="mono" style="font-size:12px">{{ fmtAgo(row.updated_at) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click.stop="openDocView(row)">查看</el-button>
            <el-button size="small" text type="warning" @click.stop="openDocEdit(row)">更新</el-button>
            <el-button size="small" text type="danger" @click.stop="doDeleteDoc(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- ============ 添加文档弹窗 ============ -->
    <el-dialog v-model="addDialog" title="添加文档" width="480px">
      <div class="form-label">标题</div>
      <el-input v-model="addForm.title" placeholder="文档标题" />
      <div class="form-label">类型</div>
      <el-select v-model="addForm.doc_type" style="width: 100%">
        <el-option v-for="t in ['案例', '规程', '预案', '其他']" :key="t" :label="t" :value="t" />
      </el-select>
      <div class="form-label">标签（逗号分隔，首个标签将挂为图谱概念节点）</div>
      <el-input v-model="addForm.tags" placeholder="如：抽油机, 电流" />
      <div class="form-label">内容 / 摘要</div>
      <el-input v-model="addForm.summary" type="textarea" :rows="6" placeholder="文档内容或核心摘要…" />
      <template #footer>
        <el-button @click="addDialog = false">取消</el-button>
        <el-button type="primary" :loading="acting" @click="doAddDoc">保存并入库</el-button>
      </template>
    </el-dialog>

    <!-- ============ 文档详情抽屉（查看 + 更新） ============ -->
    <el-drawer v-model="docDrawer" :title="docForm.title || '文档详情'" size="480px">
      <template v-if="docTarget">
        <div class="doc-meta">
          <el-tag size="small" effect="plain">{{ docTarget.doc_type }}</el-tag>
          <el-tag :type="INDEX_TAG[docTarget.status as IndexStatus]" size="small" effect="dark">{{ INDEX_CN[docTarget.status as IndexStatus] }}</el-tag>
          <span class="mono doc-id">{{ docTarget.doc_id }}</span>
        </div>
        <div class="doc-sub mono">来源 {{ docTarget.source_ref }} · 分块 {{ docTarget.chunk_count }} · 更新 {{ fmtAgo(docTarget.updated_at) }}</div>

        <template v-if="!docEditing">
          <div class="doc-summary">{{ docForm.summary }}</div>
          <div class="doc-tags">
            <el-tag v-for="t in docTarget.tags" :key="t" size="small" effect="plain">{{ t }}</el-tag>
          </div>
          <el-button type="warning" plain style="width:100%; margin-top:14px" @click="docEditing = true">更新文档</el-button>
        </template>

        <template v-else>
          <div class="form-label">标题</div>
          <el-input v-model="docForm.title" />
          <div class="form-label">内容 / 摘要</div>
          <el-input v-model="docForm.summary" type="textarea" :rows="8" />
          <div class="doc-drawer-actions">
            <el-button @click="docEditing = false">取消</el-button>
            <el-button type="primary" :loading="acting" @click="doUpdateDoc">保存并触发重建</el-button>
          </div>
        </template>
      </template>
    </el-drawer>

    <!-- ============ 检索测试 ============ -->
    <div v-show="tab === 'search'" class="tab-body">
      <div class="search-cols">
        <div class="search-form panel-card">
          <div class="form-label">查询语句</div>
          <el-input v-model="searchForm.query" type="textarea" :rows="3" placeholder="例如：井口压力超限怎么处置" @keydown.ctrl.enter="doSearch" />
          <div class="form-label">过滤井号</div>
          <el-select v-model="searchForm.well" clearable placeholder="全部井">
            <el-option v-for="w in WELLS" :key="w.well_id" :label="w.well_id" :value="w.well_id" />
          </el-select>
          <div class="form-label">TopK：{{ searchForm.topK }}</div>
          <el-slider v-model="searchForm.topK" :min="1" :max="10" />
          <el-button type="primary" style="width:100%" :loading="searching" @click="doSearch">检索</el-button>
          <div v-if="elapsedMs != null" class="elapsed mono">召回耗时 {{ elapsedMs }} ms</div>
        </div>

        <div class="search-results">
          <EmptyState
            v-if="searched && !hits.length" title="未命中任何分块"
            desc="换个关键词试试，或先到候选队列采纳新知识" action-text="去候选队列" @action="tab = 'candidates'"
          />
          <EmptyState v-else-if="!searched" title="输入查询开始检索" desc="用于验证新入库条目是否生效" />
          <div v-for="hit in hits" :key="hit.chunk_id" class="hit-card panel-card">
            <div class="hit-head">
              <el-tag size="small" effect="plain">{{ hit.type }}</el-tag>
              <span class="hit-title">{{ hit.title }}</span>
              <span class="mono hit-ref">{{ hit.source_ref }}</span>
            </div>
            <div class="hit-text" v-html="highlight(hit.text)" />
            <div class="hit-foot">
              <span class="mono score-label">score {{ hit.score }}</span>
              <el-progress :percentage="Math.min(hit.score / 10 * 100, 100)" :stroke-width="6" :show-text="false" class="score-bar" />
              <el-button size="small" text type="primary" @click="locateDoc">定位到文档</el-button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ============ 驳回弹窗 ============ -->
    <el-dialog v-model="rejectDlg" title="驳回候选" width="440px">
      <div class="preset-chips">
        <span
          v-for="r in REJECT_PRESETS" :key="r"
          class="preset-chip" :class="{ on: rejectNote === r }"
          @click="rejectNote = r"
        >{{ r }}</span>
      </div>
      <el-input v-model="rejectNote" type="textarea" :rows="3" placeholder="驳回原因（必填）" />
      <template #footer>
        <el-button @click="rejectDlg = false">取消</el-button>
        <el-button type="danger" :loading="acting" @click="doReject">确认驳回</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, h, nextTick, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import {
  addDocument, approveCandidate, deleteDocument, listCandidates, listDocuments, rejectCandidate, searchKnowledge, updateDocument,
} from '@/api'
import { WELLS } from '@/api/mock/data'
import { useAppStore } from '@/stores/app'
import { fmtAgo } from '@/utils/format'
import type { IndexStatus, KBCandidate, KBDocumentView, SearchHit } from '@/api/types'

const route = useRoute()
const router = useRouter()
const app = useAppStore()

/** 支持从告警页 toast 带 tab 参数跳入；从对话「查看来源」带 doc 参数定位到具体文档 */
const tab = ref((route.query.tab as string) || 'candidates')
const focusDocId = ref((route.query.doc as string) || '')
const docTableRef = ref()

function docRowClass({ row }: { row: KBDocumentView }) {
  return row.doc_id === focusDocId.value ? 'doc-row-focus' : ''
}

/** 定位到目标文档：切到 docs tab → 等表格渲染完 → 滚动到该行 → 直接打开详情抽屉 */
async function locateDocById() {
  if (!focusDocId.value) return
  tab.value = 'docs'
  await nextTick()
  await nextTick() // el-table 行渲染需要两拍
  const el = docTableRef.value?.$el?.querySelector?.('.doc-row-focus') as HTMLElement | null
  el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  // 「查看来源」跳入时直接打开文档内容，不止高亮行
  const doc = docs.value.find(d => d.doc_id === focusDocId.value)
  if (doc) openDocView(doc)
}

const SOURCE_CN = { workorder: '工单', alert_dedup: '告警', trace: '对话' } as const
const INDEX_CN: Record<IndexStatus, string> = { pending: '待索引', indexing: '索引中', ready: '已就绪', failed: '失败' }
const INDEX_TAG: Record<IndexStatus, 'info' | 'warning' | 'success' | 'danger'> = { pending: 'info', indexing: 'warning', ready: 'success', failed: 'danger' }

/* ---------- 文档查看 / 更新抽屉 ---------- */
const docDrawer = ref(false)
const docEditing = ref(false)
const docTarget = ref<KBDocumentView | null>(null)
const docForm = reactive({ title: '', summary: '' })

function openDocView(row: KBDocumentView) {
  docTarget.value = row
  docForm.title = row.title
  docForm.summary = row.summary
  docEditing.value = false
  docDrawer.value = true
}
function openDocEdit(row: KBDocumentView) {
  openDocView(row)
  docEditing.value = true
}

/** 保存更新：回写 mock + 触发图谱重建（自进化闭环） */
async function doUpdateDoc() {
  if (!docTarget.value) return
  if (!docForm.title.trim() || !docForm.summary.trim()) { ElMessage.warning('标题与内容不能为空'); return }
  acting.value = true
  try {
    const { graph_version } = await updateDocument(docTarget.value.doc_id, docForm.title.trim(), docForm.summary.trim())
    docEditing.value = false
    notifyGraphRebuild('文档已更新', graph_version)
    await reload()
  } finally { acting.value = false }
}

/* ---------- 添加 / 删除文档 ---------- */
const addDialog = ref(false)
const addForm = reactive({ title: '', doc_type: '案例', tags: '', summary: '' })

function notifyGraphRebuild(prefix: string, version: number) {
  ElMessage({
    type: 'success', duration: 5000,
    message: h('span', null, [
      `${prefix} · 已触发图谱重建 v${version} `,
      h('a', {
        style: 'color: var(--accent-hover); cursor: pointer; text-decoration: underline;',
        onClick: () => router.push('/graph'),
      }, '查看图谱'),
    ]),
  })
}

async function doAddDoc() {
  if (!addForm.title.trim() || !addForm.summary.trim()) { ElMessage.warning('标题与内容不能为空'); return }
  acting.value = true
  try {
    const tags = addForm.tags.split(/[,，]/).map(s => s.trim()).filter(Boolean)
    const { graph_version } = await addDocument({ title: addForm.title.trim(), summary: addForm.summary.trim(), doc_type: addForm.doc_type, tags })
    addDialog.value = false
    Object.assign(addForm, { title: '', doc_type: '案例', tags: '', summary: '' })
    notifyGraphRebuild('文档已入库', graph_version)
    await reload()
  } finally { acting.value = false }
}

async function doDeleteDoc(row: KBDocumentView) {
  try {
    await ElMessageBox.confirm(`删除文档「${row.title}」？将同步从图谱摘除该文档节点。`, '确认删除', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
  } catch { return }
  acting.value = true
  try {
    const { graph_version } = await deleteDocument(row.doc_id)
    notifyGraphRebuild('文档已删除', graph_version)
    await reload()
  } finally { acting.value = false }
}

/* ---------- 候选队列 ---------- */
const candidates = ref<KBCandidate[]>([])
const docs = ref<KBDocumentView[]>([])
const sourceFilter = ref('')
const checkedIds = reactive(new Set<string>())
const acting = ref(false)

async function reload() {
  const [c, d] = await Promise.all([listCandidates('pending'), listDocuments()])
  candidates.value = c.items
  docs.value = d.items
  // 数据到位后再定位（初次带 doc query 跳入时）
  locateDocById()
}
reload()

const filteredCandidates = computed(() =>
  sourceFilter.value ? candidates.value.filter(c => c.source_type === sourceFilter.value) : candidates.value,
)

function toggleCheck(id: string) {
  checkedIds.has(id) ? checkedIds.delete(id) : checkedIds.add(id)
}

/* 采纳：先内联编辑，确认后入库并触发图谱重建 */
const editingId = ref('')
const editForm = reactive({ title: '', text: '', tags: [] as string[] })

function startEdit(c: KBCandidate) {
  editingId.value = c.candidate_id
  Object.assign(editForm, { title: c.title, text: c.text, tags: [...c.tags] })
}

async function doApprove(c: KBCandidate) {
  acting.value = true
  try {
    // 编辑结果回写本地对象（mock：让队列展示与入库内容一致）
    Object.assign(c, { title: editForm.title, text: editForm.text, tags: editForm.tags })
    const { graph_version } = await approveCandidate(c.candidate_id)
    editingId.value = ''
    checkedIds.delete(c.candidate_id)
    // 自进化可见：toast 带重建版本号 + 跳转链接
    ElMessage({
      type: 'success', duration: 6000,
      message: h('span', null, [
        `已入库 · 已触发知识图谱重建 v${graph_version} `,
        h('a', {
          style: 'color: var(--accent-hover); cursor: pointer; text-decoration: underline;',
          onClick: () => router.push('/graph'),
        }, '查看重建进度'),
      ]),
    })
    app.refreshSummary()
    reload()
  } finally { acting.value = false }
}

/* 驳回（二次确认在弹窗内完成，原因必填） */
const REJECT_PRESETS = ['内容重复', '口径有误', '信息不完整', '非通用经验', '涉及敏感信息']
const rejectDlg = ref(false)
const rejectNote = ref('')
const rejectingId = ref('')

function openReject(c: KBCandidate) {
  rejectingId.value = c.candidate_id
  rejectNote.value = ''
  rejectDlg.value = true
}

async function doReject() {
  if (!rejectNote.value.trim()) { ElMessage.warning('驳回原因必填：请点选或手动填写'); return }
  acting.value = true
  try {
    await rejectCandidate(rejectingId.value, rejectNote.value.trim())
    rejectDlg.value = false
    ElMessage.success('已驳回')
    reload()
  } finally { acting.value = false }
}

async function batchApprove() {
  acting.value = true
  try {
    let version = 0
    for (const id of [...checkedIds]) {
      const r = await approveCandidate(id)
      version = r.graph_version
    }
    ElMessage.success(`已批量采纳 ${checkedIds.size} 条，图谱重建至 v${version}`)
    checkedIds.clear()
    app.refreshSummary()
    reload()
  } finally { acting.value = false }
}

async function batchReject() {
  const { value } = await ElMessageBox.prompt('批量驳回原因', '批量驳回', { inputValidator: v => !!v?.trim() || '原因必填' })
  acting.value = true
  try {
    for (const id of [...checkedIds]) await rejectCandidate(id, value.trim())
    ElMessage.success(`已批量驳回 ${checkedIds.size} 条`)
    checkedIds.clear()
    reload()
  } finally { acting.value = false }
}

/* ---------- 检索测试 ---------- */
const searchForm = reactive({ query: '', well: '', topK: 5 })
const hits = ref<SearchHit[]>([])
const elapsedMs = ref<number | null>(null)
const searching = ref(false)
const searched = ref(false)

async function doSearch() {
  if (!searchForm.query.trim()) { ElMessage.warning('请输入查询语句'); return }
  searching.value = true
  try {
    const r = await searchKnowledge(
      searchForm.well ? `${searchForm.well} ${searchForm.query}` : searchForm.query,
      searchForm.topK,
    )
    hits.value = r.hits
    elapsedMs.value = r.elapsed_ms
    searched.value = true
  } finally { searching.value = false }
}

/** 关键词高亮（与后端切词口径一致） */
function highlight(text: string): string {
  const keys = searchForm.query.split(/[\s，,。？?]+/).filter(Boolean)
  let out = text
  for (const k of keys) out = out.split(k).join(`<mark>${k}</mark>`)
  return out
}

function locateDoc() { tab.value = 'docs' }
</script>

<style scoped>
.knowledge-view { display: flex; flex-direction: column; height: 100%; min-height: 0; }

.kb-tabs { flex: none; padding: 0 16px; background: var(--bg-panel); border-bottom: 1px solid var(--border); }
.kb-tabs :deep(.el-tabs__header) { margin: 0; }
.kb-tabs :deep(.el-tabs__nav-wrap::after) { display: none; }

.tab-body { flex: 1; min-height: 0; display: flex; flex-direction: column; }

/* 候选队列 */
.cand-toolbar {
  flex: none; display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; border-bottom: 1px solid var(--border);
}
.cand-toolbar .spacer { flex: 1; }
.hint { color: var(--text-disabled); font-size: 12px; }

.cand-scroll {
  flex: 1; overflow-y: auto; padding: 16px;
  display: flex; flex-direction: column; gap: 12px; align-items: center;
}
.cand-card { width: 100%; max-width: 900px; padding: 14px 18px; }

.cand-head { display: flex; align-items: center; gap: 10px; }
.source-badge {
  font-size: 11px; font-weight: 600; padding: 1px 8px; border-radius: var(--radius-tag);
  border: 1px solid transparent;
}
.source-badge.workorder { color: var(--source-workorder); background: rgba(88,166,255,.12); border-color: rgba(88,166,255,.4); }
.source-badge.alert_dedup { color: var(--source-alert); background: rgba(210,153,34,.12); border-color: rgba(210,153,34,.4); }
.source-badge.trace { color: var(--source-trace); background: rgba(188,140,255,.12); border-color: rgba(188,140,255,.4); }
.cand-title { font-weight: 600; font-size: 14.5px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cand-time { color: var(--text-disabled); font-size: 12px; flex: none; }

.cand-text {
  margin-top: 10px; font-size: 13px; color: var(--text-secondary); line-height: 1.7;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
  white-space: pre-wrap;
}
.cand-meta { margin-top: 8px; font-size: 11.5px; color: var(--text-disabled); }
.cand-actions { display: flex; gap: 8px; margin-top: 12px; }
.edit-field { margin-top: 10px; }

/* 文档库 */
.doc-table { flex: 1; padding: 16px; }
/* 「查看来源」跳入的目标行：高亮 + 呼吸边框 */
.doc-table :deep(.doc-row-focus) {
  background: rgba(47,129,247,.14) !important;
  box-shadow: inset 2px 0 0 var(--accent);
  animation: docFocusPulse 2.4s ease-in-out 2;
}
.doc-table :deep(.doc-row-focus:hover > td) { background: rgba(47,129,247,.2) !important; }
@keyframes docFocusPulse {
  0%, 100% { background: rgba(47,129,247,.10); }
  50% { background: rgba(47,129,247,.26); }
}

/* 检索测试 */
.search-cols { flex: 1; min-height: 0; display: flex; gap: 16px; padding: 16px; }
.search-form {
  width: 300px; flex: none; padding: 16px; height: fit-content;
  display: flex; flex-direction: column; gap: 6px;
}
.form-label { font-size: 12.5px; color: var(--text-secondary); margin-top: 6px; }
.elapsed { text-align: center; color: var(--level-ok); font-size: 12px; margin-top: 8px; }

.search-results { flex: 1; min-width: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.hit-card { padding: 14px 16px; }
.hit-head { display: flex; align-items: center; gap: 8px; }
.hit-title { font-weight: 600; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hit-ref { color: var(--text-disabled); font-size: 11.5px; }
.hit-text { margin-top: 8px; font-size: 13px; color: var(--text-secondary); line-height: 1.7; }
.hit-text :deep(mark) { background: rgba(210,153,34,.35); color: var(--text-primary); border-radius: 2px; padding: 0 2px; }
.hit-foot { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.score-label { font-size: 12px; color: var(--accent-hover); flex: none; }
.score-bar { flex: 1; }

/* 驳回弹窗快选 */
.preset-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.preset-chip {
  font-size: 12px; padding: 2px 10px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--border-strong); color: var(--text-secondary);
  transition: all .15s ease-out;
}
.preset-chip:hover { border-color: var(--accent); color: var(--accent-hover); }
.preset-chip.on { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-hover); }

/* 文档详情抽屉 */
.doc-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.docs-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.docs-count { color: var(--text-disabled); font-size: 12px; }
.doc-id { font-size: 12px; color: var(--text-disabled); }
.doc-sub { color: var(--text-disabled); font-size: 12px; margin-bottom: 14px; }
.doc-summary {
  font-size: 13.5px; line-height: 1.8; color: var(--text-primary);
  background: var(--bg-elevated); border: 1px solid var(--border);
  border-radius: var(--radius-card); padding: 12px 14px; white-space: pre-wrap;
}
.doc-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.doc-drawer-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 14px; }
/* 文档库行可点击 */
.doc-table :deep(.el-table__row) { cursor: pointer; }
</style>
