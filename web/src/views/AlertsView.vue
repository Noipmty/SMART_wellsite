<template>
  <div class="alerts-view">
    <!-- ============ 筛选栏（状态同步 URL query，可刷新恢复/分享） ============ -->
    <header class="filter-bar">
      <el-select v-model="filters.status" placeholder="状态" style="width: 110px" @change="reload">
        <el-option label="全部状态" value="" />
        <el-option v-for="(cn, k) in STATUS_CN" :key="k" :label="cn" :value="k" />
      </el-select>
      <el-select v-model="filters.level" placeholder="等级" style="width: 100px" @change="reload">
        <el-option label="全部等级" value="" />
        <el-option v-for="l in LEVEL_ORDER" :key="l" :label="l" :value="l" />
      </el-select>
      <el-select v-model="filters.well_id" placeholder="井号" filterable style="width: 110px" @change="reload">
        <el-option label="全部井" value="" />
        <el-option v-for="w in WELLS" :key="w.well_id" :label="w.well_id" :value="w.well_id" />
      </el-select>
      <el-checkbox v-model="filters.overtime" @change="reload">仅看超时</el-checkbox>
      <el-input
        v-model="filters.keyword" placeholder="搜索摘要…" clearable style="width: 180px"
        :prefix-icon="Search" @input="debouncedReload"
      />
      <div class="filter-right">
        <span class="mono count-hint">{{ displayed.length }} / {{ alerts.length }} 条</span>
        <!-- 排序方式：优先级 / 最新优先 / 最早优先（同步 URL query，可刷新恢复） -->
        <el-select v-model="sortBy" style="width: 120px" size="small">
          <el-option label="按优先级" value="priority" />
          <el-option label="最新优先" value="latest" />
          <el-option label="最早优先" value="earliest" />
        </el-select>
        <el-checkbox v-model="overtimeTop">超时置顶</el-checkbox>
      </div>
    </header>

    <div class="alerts-body">
      <!-- ============ 左：告警列表 ============ -->
      <aside class="alert-list">
        <div class="list-scroll" ref="listRef">
          <EmptyState
            v-if="!displayed.length"
            title="没有匹配的告警" desc="调整筛选条件，或等下一轮巡检"
            action-text="清除筛选" @action="clearFilters"
          />
          <AlarmCard
            v-for="(a, i) in displayed" :key="a.alert_id"
            :alert="a" :selected="selected?.alert_id === a.alert_id"
            :checked="checkedIds.has(a.alert_id)"
            :class="{ 'kbd-focus': i === kbdIndex }"
            @select="select" @check="toggleCheck"
          />
        </div>

        <!-- 批量操作浮条 -->
        <transition name="fade">
          <div v-if="checkedIds.size" class="batch-bar">
            <span>已选 <b class="mono">{{ checkedIds.size }}</b> 条</span>
            <el-button size="small" type="primary" plain @click="batchAck">批量确认</el-button>
            <el-button size="small" type="warning" plain @click="batchResolve">批量关闭</el-button>
            <el-button size="small" text @click="checkedIds.clear()">清除</el-button>
          </div>
        </transition>
      </aside>

      <!-- ============ 右：告警详情 ============ -->
      <section class="alert-detail">
        <template v-if="selected">
          <div class="detail-head panel-card">
            <div class="detail-title">
              <span class="mono well-id">{{ selected.scope }}</span>
              <h3>{{ selected.cause }}</h3>
              <LevelTag :level="selected.level" />
              <span v-if="selected.overtime" class="overtime-tag">超时未处置</span>
            </div>
            <div class="detail-sub mono">
              {{ selected.alert_id }} · 首报 {{ fmtFull(selected.first_seen) }} · hit {{ selected.hit_count }} 次 · 抑制 {{ selected.suppressed_count }} 次
            </div>
            <div class="detail-content">{{ selected.content }}</div>
            <div class="detail-actions">
              <el-button
                v-if="selected.status === 'active'" type="primary" :loading="acting"
                @click="ackSelected"
              >确认告警</el-button>
              <el-button
                v-if="selected.status !== 'resolved'" type="warning" plain :loading="acting"
                @click="resolveSelected"
              >标记已解决</el-button>
            </div>
          </div>

          <div class="detail-cols">
            <!-- 等级时间线 -->
            <div class="panel-card detail-block">
              <div class="block-title">等级时间线</div>
              <el-timeline>
                <el-timeline-item
                  v-for="(it, i) in timeline" :key="i"
                  :timestamp="fmtShort(it.ts)" :type="it.type" :hollow="i !== timeline.length - 1"
                >
                  <b>{{ it.label }}</b>
                  <div class="tl-note">{{ it.note }}</div>
                </el-timeline-item>
              </el-timeline>
            </div>

            <!-- 关联工单状态机 -->
            <div class="panel-card detail-block">
              <div class="block-title">
                关联工单
                <span v-if="order" class="mono order-id">{{ order.order_id }}</span>
              </div>
              <template v-if="order">
                <!-- key 绑定状态：每次流转强制重渲染，保证步骤条实时跟随 -->
                <el-steps :key="`${order.order_id}-${order.status}`" :active="stepActive" align-center finish-status="success" class="order-steps">
                  <el-step title="指派" :description="order.assignee ? `处理人：${order.assignee}` : '待指派'" />
                  <el-step title="处理" :description="order.resolution ? '已填处置结果' : '处置中'" />
                  <el-step title="关闭" :description="order.status === 'closed' ? '已回填实际原因' : ''" />
                </el-steps>

                <div v-if="order.resolution" class="order-line"><span>处置结果</span>{{ order.resolution }}</div>
                <div v-if="order.actual_cause" class="order-line"><span>实际原因</span>{{ order.actual_cause }}</div>

                <div class="order-actions">
                  <el-button v-if="order.status === 'pending'" type="primary" :loading="acting" @click="assignToMe">
                    ① 指派给我
                  </el-button>
                  <el-button v-else-if="order.status === 'processing'" type="primary" :loading="acting" @click="resolveOrderDlg = true">
                    ② 填写处置结果
                  </el-button>
                  <el-button v-else-if="order.status === 'resolved'" type="warning" :loading="acting" @click="openCloseDlg">
                    ③ 关闭工单
                  </el-button>
                  <el-tag v-else type="success" effect="dark">已关闭 · 已闭环</el-tag>
                </div>

                <!-- 流转记录：每次状态变更落一条（类派单分状态存储） -->
                <div v-if="order.escalations.length" class="flow-records">
                  <div class="block-sub">流转记录</div>
                  <div v-for="(r, i) in [...order.escalations].reverse()" :key="i" class="flow-row">
                    <span class="mono flow-ts">{{ fmtShort(r.ts) }}</span>
                    <span class="flow-change">{{ WO_STATUS_CN[r.from_level] ?? r.from_level }} → {{ WO_STATUS_CN[r.to_level] ?? r.to_level }}</span>
                    <span class="flow-note">{{ r.note }}</span>
                  </div>
                </div>
              </template>
              <EmptyState v-else title="未生成工单" desc="该告警尚未派单，确认告警后将自动生成" />

              <!-- 协同链路简化版 -->
              <div v-if="selected.trace_id" class="trace-simple">
                <div class="block-title">协同链路</div>
                <div class="trace-row mono">{{ selected.trace_id }}</div>
                <div class="trace-row">来源 Agent：{{ agentCn(selected.source) }}</div>
              </div>
            </div>
          </div>
        </template>

        <EmptyState
          v-else title="选择左侧告警查看详情"
          desc="支持 ↑ / ↓ 键切换，Enter 打开"
        />
      </section>
    </div>

    <!-- ============ 填写处置结果弹窗 ============ -->
    <el-dialog v-model="resolveOrderDlg" title="填写处置结果" width="440px">
      <el-input v-model="resolveText" type="textarea" :rows="3" placeholder="例如：已调整针阀开度，压力回落至 1.35 MPa" />
      <template #footer>
        <el-button @click="resolveOrderDlg = false">取消</el-button>
        <el-button type="primary" :loading="acting" @click="doResolveOrder">提交</el-button>
      </template>
    </el-dialog>

    <!-- ============ 关闭工单弹窗：actual_cause 必填 + 沉淀知识 ============ -->
    <el-dialog v-model="closeDlg" title="关闭工单" width="520px">
      <div class="close-form">
        <div class="form-label required">实际原因 actual_cause</div>
        <div class="preset-chips">
          <span
            v-for="p in CLOSE_CAUSE_PRESETS" :key="p"
            class="preset-chip" :class="{ on: closeForm.cause === p }"
            @click="closeForm.cause = p"
          >{{ p }}</span>
        </div>
        <el-input
          v-model="closeForm.cause" type="textarea" :rows="3"
          placeholder="必填：选择上方常见原因，或自由填写实际原因"
        />
        <el-checkbox v-model="closeForm.distill" class="distill-check">
          沉淀为知识候选（推荐：处置经验将进入候选队列，运营采纳后触发图谱重建）
        </el-checkbox>
      </div>
      <template #footer>
        <el-button @click="closeDlg = false">取消</el-button>
        <el-button type="warning" :loading="acting" @click="doCloseOrder">
          关闭工单
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import AlarmCard from '@/components/AlarmCard.vue'
import EmptyState from '@/components/EmptyState.vue'
import LevelTag from '@/components/LevelTag.vue'
import {
  acknowledgeAlert, assignOrder, closeOrder, isOvertime,
  listAlerts, listWorkOrders, resolveAlert, resolveOrder,
} from '@/api'
import { agentCn } from '@/api/mock/engine'
import { CLOSE_CAUSE_PRESETS, LEVEL_ORDER, WELLS } from '@/api/mock/data'
import { usePolling } from '@/composables/usePolling'
import { useAppStore } from '@/stores/app'
import { fmtFull, fmtShort } from '@/utils/format'
import type { Alert, Level, WorkOrder } from '@/api/types'

const route = useRoute()
const router = useRouter()
const app = useAppStore()

const STATUS_CN = { active: '活动', acknowledged: '已确认', resolved: '已解决' } as const

/** 工单状态机中文映射（流转记录展示用） */
const WO_STATUS_CN: Record<string, string> = { pending: '待指派', processing: '处理中', resolved: '待关闭', closed: '已关闭' }

/* ---------- 筛选（与 URL query 双向同步） ---------- */
const filters = reactive({
  status: (route.query.status as string) || '',
  level: (route.query.level as Level) || '',
  well_id: (route.query.well as string) || '',
  overtime: route.query.overtime === '1',
  keyword: (route.query.q as string) || '',
})
watch(filters, () => {
  router.replace({ query: {
    ...(filters.status ? { status: filters.status } : {}),
    ...(filters.level ? { level: filters.level } : {}),
    ...(filters.well_id ? { well: filters.well_id } : {}),
    ...(filters.overtime ? { overtime: '1' } : {}),
    ...(filters.keyword ? { q: filters.keyword } : {}),
  } })
})

let debounceTimer: ReturnType<typeof setTimeout> | null = null
function debouncedReload() {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(reload, 300)
}

/* ---------- 数据加载（30s 轮询） ---------- */
const alerts = ref<Alert[]>([])
const orders = ref<WorkOrder[]>([])
const overtimeTop = ref(true)
const acting = ref(false)

/* ---------- 排序方式（同步 URL query） ---------- */
type SortBy = 'priority' | 'latest' | 'earliest'
const sortBy = ref<SortBy>((route.query.sort as SortBy) || 'priority')
watch(sortBy, v => {
  router.replace({ query: { ...route.query, ...(v !== 'priority' ? { sort: v } : {}) } })
})

/** 状态权重：已解决固定沉底，其余未处置在上 */
const STATUS_W: Record<string, number> = { active: 0, acknowledged: 1, resolved: 2 }
/** 等级权重：高危在前（紧急 > 预警 > 提醒 > 提示） */
const LEVEL_W: Record<Level, number> = { 紧急: 0, 预警: 1, 提醒: 2, 提示: 3 }

async function reload() {
  const [a, o] = await Promise.all([
    listAlerts({ status: filters.status || undefined, level: (filters.level as Level) || undefined, well_id: filters.well_id || undefined }),
    listWorkOrders(),
  ])
  alerts.value = a.items
  orders.value = o.items
  // 保持选中对象引用最新（状态可能已被轮询更新）
  if (selected.value) selected.value = alerts.value.find(x => x.alert_id === selected.value!.alert_id) ?? null
}
usePolling(reload, 30_000)

/** 展示列表：客户端叠加超时/关键词过滤 + 排序（已解决恒沉底） */
const displayed = computed(() => {
  let list = alerts.value
  if (filters.overtime) list = list.filter(a => a.overtime)
  if (filters.keyword.trim()) {
    const k = filters.keyword.trim()
    list = list.filter(a => a.content.includes(k) || a.cause.includes(k) || a.scope.includes(k))
  }
  return [...list].sort((a, b) => {
    // ① 状态：已解决恒沉底
    const sw = STATUS_W[a.status] - STATUS_W[b.status]
    if (sw) return sw
    // ② 超时置顶开关（仅影响未解决组内）
    if (overtimeTop.value && a.overtime !== b.overtime) return a.overtime ? -1 : 1
    // ③ 排序方式
    if (sortBy.value === 'priority') {
      const lw = LEVEL_W[a.level] - LEVEL_W[b.level]
      if (lw) return lw // 高危在前
      return +new Date(b.last_seen) - +new Date(a.last_seen) // 同级按最新
    }
    if (sortBy.value === 'earliest') return +new Date(a.last_seen) - +new Date(b.last_seen)
    return +new Date(b.last_seen) - +new Date(a.last_seen) // latest
  })
})

function clearFilters() {
  Object.assign(filters, { status: '', level: '', well_id: '', overtime: false, keyword: '' })
  reload()
}

/* ---------- 选中 / 键盘导航 ---------- */
const selected = ref<Alert | null>(null)
const kbdIndex = ref(-1)
const listRef = ref<HTMLElement>()

function select(a: Alert) {
  selected.value = a
  kbdIndex.value = displayed.value.findIndex(x => x.alert_id === a.alert_id)
}

function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement
  if (['INPUT', 'TEXTAREA'].includes(target.tagName)) return
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    const delta = e.key === 'ArrowDown' ? 1 : -1
    kbdIndex.value = Math.min(Math.max(kbdIndex.value + delta, 0), displayed.value.length - 1)
    // 让焦点项滚入视野
    listRef.value?.children[kbdIndex.value]?.scrollIntoView({ block: 'nearest' })
  } else if (e.key === 'Enter' && kbdIndex.value >= 0 && displayed.value[kbdIndex.value]) {
    select(displayed.value[kbdIndex.value])
  }
}
onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

/* ---------- 批量操作 ---------- */
const checkedIds = reactive(new Set<string>())
function toggleCheck(a: Alert) {
  checkedIds.has(a.alert_id) ? checkedIds.delete(a.alert_id) : checkedIds.add(a.alert_id)
}
async function batchAck() {
  const targets = alerts.value.filter(a => checkedIds.has(a.alert_id) && a.status === 'active')
  for (const a of targets) await acknowledgeAlert(a.alert_id, app.dutyUser)
  ElMessage.success(`已确认 ${targets.length} 条告警`)
  checkedIds.clear(); reload(); app.refreshSummary()
}
async function batchResolve() {
  const targets = alerts.value.filter(a => checkedIds.has(a.alert_id) && a.status !== 'resolved')
  if (!targets.length) { ElMessage.info('所选告警均已是已解决状态'); return }
  await ElMessageBox.confirm(`将批量关闭 ${targets.length} 条告警（处置口径：集中核查）？`, '批量关闭', { type: 'warning' })
  for (const a of targets) await resolveAlert(a.alert_id, app.dutyUser, '批量处置：集中核查无异常')
  ElMessage.success(`已批量关闭 ${targets.length} 条告警`)
  checkedIds.clear(); reload(); app.refreshSummary()
}

/* ---------- 详情：确认 / 解决告警 ---------- */
async function ackSelected() {
  if (!selected.value) return
  acting.value = true
  try {
    await acknowledgeAlert(selected.value.alert_id, app.dutyUser)
    ElMessage.success('告警已确认')
    await reload(); app.refreshSummary()
  } finally { acting.value = false }
}
async function resolveSelected() {
  if (!selected.value) return
  const { value } = await ElMessageBox.prompt('填写处置说明', '标记已解决', { inputPlaceholder: '例如：现场核查已恢复正常', inputValidator: v => !!v?.trim() || '处置说明必填' })
  acting.value = true
  try {
    await resolveAlert(selected.value.alert_id, app.dutyUser, value.trim())
    ElMessage.success('告警已标记解决')
    await reload(); app.refreshSummary()
  } finally { acting.value = false }
}

/* ---------- 关联工单状态机 ---------- */
const order = computed(() => orders.value.find(o => o.alert_id === selected.value?.alert_id))
const STEP_MAP: Record<WorkOrder['status'], number> = { pending: 0, processing: 1, resolved: 2, closed: 3 }
const stepActive = computed(() => order.value ? STEP_MAP[order.value.status] : 0)

async function assignToMe() {
  if (!order.value) return
  acting.value = true
  try {
    await assignOrder(order.value.order_id, app.dutyUser)
    ElMessage.success(`已指派给 ${app.dutyUser}`)
    await reload()
  } finally { acting.value = false }
}

const resolveOrderDlg = ref(false)
const resolveText = ref('')
async function doResolveOrder() {
  if (!order.value) return
  if (!resolveText.value.trim()) { ElMessage.warning('请填写处置结果'); return }
  acting.value = true
  try {
    await resolveOrder(order.value.order_id, resolveText.value.trim())
    resolveOrderDlg.value = false; resolveText.value = ''
    ElMessage.success('处置结果已提交')
    await reload()
  } finally { acting.value = false }
}

/* ---------- 关闭工单 → 沉淀知识候选（自进化闭环） ---------- */
const closeDlg = ref(false)
const closeForm = reactive({ cause: '', distill: true })
function openCloseDlg() { closeForm.cause = ''; closeForm.distill = true; closeDlg.value = true }

async function doCloseOrder() {
  if (!order.value) return
  // actual_cause 必填：提交时校验，避免按钮 disabled 状态阻塞流程
  if (!closeForm.cause.trim()) { ElMessage.warning('实际原因必填：请点选常见原因或手动填写'); return }
  acting.value = true
  try {
    const { candidate } = await closeOrder(order.value.order_id, closeForm.cause.trim(), closeForm.distill)
    closeDlg.value = false
    // 闭环可见：toast 带“去知识运营查看”链接
    ElMessage({
      type: 'success', duration: 6000,
      message: h('span', null, [
        candidate ? '已关闭 · 已沉淀为知识候选，待运营采纳 ' : '已关闭 ',
        candidate ? h('a', {
          style: 'color: var(--accent-hover); cursor: pointer; text-decoration: underline;',
          onClick: () => router.push('/knowledge'),
        }, '去知识运营查看') : null,
      ]),
    })
    await reload(); app.refreshSummary()
  } finally { acting.value = false }
}

/* ---------- 等级时间线组装 ---------- */
interface TlItem { ts: string; label: string; note: string; type: 'primary' | 'warning' | 'danger' | 'success' | 'info' }
const timeline = computed<TlItem[]>(() => {
  const a = selected.value
  if (!a) return []
  const items: TlItem[] = [
    { ts: a.first_seen, label: `${a.level} 触发`, note: a.content, type: a.level === '紧急' ? 'danger' : a.level === '预警' ? 'warning' : 'primary' },
    ...a.escalations.map(e => ({
      ts: e.ts, label: `升级 ${e.from_level} → ${e.to_level}`,
      note: `${e.note}（已通知：${e.notified.join('、')}）`, type: 'danger' as const,
    })),
  ]
  if (a.acknowledged_at) items.push({ ts: a.acknowledged_at, label: '确认', note: `确认人：${a.acknowledged_by}`, type: 'warning' })
  if (a.resolved_at) items.push({ ts: a.resolved_at, label: '解决', note: a.resolution ?? '', type: 'success' })
  return items.sort((x, y) => +new Date(x.ts) - +new Date(y.ts))
})
</script>

<style scoped>
.alerts-view { display: flex; flex-direction: column; height: 100%; min-height: 0; }

.filter-bar {
  flex: none; display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; border-bottom: 1px solid var(--border); background: var(--bg-panel);
}
.filter-right { margin-left: auto; display: flex; align-items: center; gap: 14px; }
.count-hint { color: var(--text-disabled); font-size: 12px; }

.alerts-body { flex: 1; display: flex; min-height: 0; }

/* 左列表 */
.alert-list {
  position: relative; width: 380px; flex: none;
  border-right: 1px solid var(--border);
  display: flex; flex-direction: column; min-height: 0;
}
.list-scroll { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.kbd-focus { outline: 1px dashed var(--accent); outline-offset: 2px; }

.batch-bar {
  position: absolute; left: 12px; right: 12px; bottom: 12px;
  display: flex; align-items: center; gap: 8px;
  background: var(--bg-elevated); border: 1px solid var(--border-strong);
  border-radius: var(--radius-card); padding: 8px 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,.6); font-size: 13px; z-index: 5;
}

/* 右详情 */
.alert-detail { flex: 1; min-width: 0; overflow-y: auto; padding: 16px; display: flex; flex-direction: column; gap: 14px; }

.detail-head { padding: 16px 18px; }
.detail-title { display: flex; align-items: center; gap: 10px; }
.detail-title h3 { margin: 0; font-size: 17px; }
.well-id { font-size: 17px; font-weight: 700; color: var(--accent-hover); }
.overtime-tag {
  font-size: 11px; font-weight: 600; color: #fff;
  background: var(--level-critical); border-radius: var(--radius-tag); padding: 1px 8px;
}
.detail-sub { color: var(--text-disabled); font-size: 12px; margin-top: 6px; }
.detail-content { color: var(--text-secondary); font-size: 13.5px; margin-top: 10px; line-height: 1.7; }
.detail-actions { display: flex; gap: 10px; margin-top: 14px; }

.detail-cols { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; align-items: start; }
@media (max-width: 1280px) { .detail-cols { grid-template-columns: 1fr; } }

.detail-block { padding: 14px 16px; }
.block-title { font-weight: 600; font-size: 14px; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.order-id { font-size: 12px; color: var(--text-disabled); font-weight: 400; }
.tl-note { color: var(--text-secondary); font-size: 12.5px; margin-top: 2px; }

.order-steps { margin: 6px 0 12px; }
.order-line { font-size: 13px; color: var(--text-primary); margin-bottom: 6px; }
.order-line span { color: var(--text-disabled); margin-right: 10px; font-size: 12px; }
.order-actions { margin-top: 10px; }

/* 流转记录 */
.flow-records { margin-top: 14px; border-top: 1px dashed var(--border); padding-top: 10px; }
.block-sub { font-size: 12px; color: var(--text-disabled); margin-bottom: 6px; }
.flow-row {
  display: flex; align-items: baseline; gap: 10px;
  font-size: 12.5px; padding: 4px 0; line-height: 1.5;
}
.flow-ts { color: var(--text-disabled); flex: none; font-size: 11.5px; }
.flow-change { color: var(--accent-hover); flex: none; font-weight: 600; }
.flow-note { color: var(--text-secondary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.trace-simple { margin-top: 14px; border-top: 1px dashed var(--border); padding-top: 12px; }
.trace-row { font-size: 12.5px; color: var(--text-secondary); margin-bottom: 4px; }

/* 关闭弹窗 */
.close-form .form-label { font-size: 13px; margin-bottom: 8px; }
.close-form .required::before { content: '*'; color: var(--level-critical); margin-right: 4px; }
.preset-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.preset-chip {
  font-size: 12px; padding: 2px 10px; border-radius: 12px; cursor: pointer;
  border: 1px solid var(--border-strong); color: var(--text-secondary);
  transition: all .15s ease-out;
}
.preset-chip:hover { border-color: var(--accent); color: var(--accent-hover); }
.preset-chip.on { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-hover); }
.distill-check { margin-top: 12px; }
</style>
