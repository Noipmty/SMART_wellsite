/* ============ API 门面：当前走 mock，切真实后端仅需把 USE_MOCK 置 false 并实现 http 分支 ============ */
import type {
  Alert, CalendarEventView, ChatResponse, GraphCommunity, GraphNode, GraphStats,
  KBCandidate, KBDocumentView, Level, NeighborItem, Page, SearchHit,
  TelemetryResult, WellView, WorkOrder, WorkOrderStatus,
} from './types'
import {
  ALERTS, CALENDAR_EVENTS, GRAPH_COMMUNITIES, GRAPH_EDGES, GRAPH_NODES,
  KB_CANDIDATES, KB_DOCS, METRICS, WELLS, WORK_ORDERS,
} from './mock/data'
import { mockChat } from './mock/engine'
import { getSeries, resumeWell, simAlerts, simOrders } from './mock/realtime'

/** 根据 id 前缀判断是否为实时模拟产生的告警/工单（内存态，不写入 localStorage） */
const isSimId = (id: string) => id.startsWith('sim-')

export const USE_MOCK = true

const delay = (ms = 220) => new Promise(r => setTimeout(r, ms + Math.random() * 180))

/* ============ 状态持久化（类派单系统：状态机变更分状态落 localStorage，刷新不丢） ============ */
const LS_KEY = 'smart-wellsite.mock.v2' // v2：纳入 docs/graphNodes/graphEdges 持久化，旧 v1 缓存自动失效

interface PersistedState {
  alerts: Alert[]
  orders: WorkOrder[]
  candidates: KBCandidate[]
  graphVersion: number
  docs: KBDocumentView[]
  graphNodes: GraphNode[]
  graphEdges: typeof GRAPH_EDGES
}

/** 每次状态变更后调用：把当前内存态整包写回 */
function persist() {
  try {
    const state: PersistedState = {
      alerts: ALERTS, orders: WORK_ORDERS, candidates: KB_CANDIDATES,
      graphVersion: graphMeta.version,
      docs: KB_DOCS, graphNodes: GRAPH_NODES, graphEdges: GRAPH_EDGES,
    }
    localStorage.setItem(LS_KEY, JSON.stringify(state))
  } catch { /* 隐私模式等场景静默忽略 */ }
}

/** 模块加载时水合：优先读 localStorage 中的持久态（文件末尾调用） */
function hydrate() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return
    const s = JSON.parse(raw) as PersistedState
    if (Array.isArray(s.alerts)) { ALERTS.length = 0; ALERTS.push(...s.alerts) }
    if (Array.isArray(s.orders)) { WORK_ORDERS.length = 0; WORK_ORDERS.push(...s.orders) }
    if (Array.isArray(s.candidates)) { KB_CANDIDATES.length = 0; KB_CANDIDATES.push(...s.candidates) }
    if (typeof s.graphVersion === 'number') graphMeta.version = s.graphVersion
    if (Array.isArray(s.docs)) { KB_DOCS.length = 0; KB_DOCS.push(...s.docs) }
    if (Array.isArray(s.graphNodes)) { GRAPH_NODES.length = 0; GRAPH_NODES.push(...s.graphNodes) }
    if (Array.isArray(s.graphEdges)) { GRAPH_EDGES.length = 0; GRAPH_EDGES.push(...s.graphEdges) }
  } catch { /* 数据损坏时回退初始 mock */ }
}

/** 工单状态流转记录：每次变更落一条，详情页展示流转历史 */
function pushTransition(o: WorkOrder, from: WorkOrderStatus, to: WorkOrderStatus, note: string) {
  o.escalations.push({ ts: new Date().toISOString(), kind: 'status', from_level: from, to_level: to, notified: [], note })
}

function page<T>(items: T[], pageNo = 1, pageSize = 20): Page<T> {
  const start = (pageNo - 1) * pageSize
  return {
    items: items.slice(start, start + pageSize),
    total: items.length, page: pageNo, page_size: pageSize,
    total_pages: Math.ceil(items.length / pageSize),
  }
}

/** 告警超时阈值：紧急 15 分钟 / 预警 60 分钟未确认即视为超时（与后端 AlertService 扫描口径一致） */
export function isOvertime(a: Alert): boolean {
  if (a.status === 'resolved') return false
  const limit = a.level === '紧急' ? 15 : a.level === '预警' ? 60 : Infinity
  return (Date.now() - new Date(a.first_seen).getTime()) / 60_000 > limit
}

// ---------------- 井场数据 ----------------
export async function listWells(): Promise<Page<WellView>> { await delay(); return page(WELLS) }

/** 从滑动窗口构造遥测结果（滑窗滚动，无静态缺口概念） */
function telemetryFromBuffer(tag: string): TelemetryResult {
  const [head, suffix] = tag.split('.')
  const metric = METRICS.find(m => m.suffix === suffix)
  return {
    tag, metric: metric?.metric ?? suffix, unit: metric?.unit ?? '',
    series: getSeries(tag), quality: { gap: [] }, events: [],
  }
}

export async function getTelemetry(tag: string, _start?: string, _end?: string): Promise<TelemetryResult> {
  await delay(180)
  return telemetryFromBuffer(tag)
}

/** 实时轮询版：无延迟直读滑动窗口（1s 节奏滚动刷新用） */
export function getTelemetryNow(tag: string): TelemetryResult {
  return telemetryFromBuffer(tag)
}

export async function eventCalendar(wellId?: string): Promise<Page<CalendarEventView>> {
  await delay()
  const items = wellId ? CALENDAR_EVENTS.filter(e => e.wells.includes(wellId)) : CALENDAR_EVENTS
  return page(items)
}

// ---------------- 对话 ----------------
export async function chat(message: string, sessionId: string): Promise<ChatResponse> {
  await delay(600) // 模拟编排耗时
  return mockChat(message, sessionId)
}

// ---------------- 告警 / 工单 ----------------
export interface AlertQuery { status?: string; level?: Level; well_id?: string }
export async function listAlerts(q: AlertQuery = {}): Promise<Page<Alert>> {
  await delay()
  // 静态 mock + 实时模拟产生的告警合并（sim 告警时间更新，排前面）
  let items = [...ALERTS, ...simAlerts]
  if (q.status) items = items.filter(a => a.status === q.status)
  if (q.level) items = items.filter(a => a.level === q.level)
  if (q.well_id) items = items.filter(a => a.scope === q.well_id)
  items.sort((a, b) => +new Date(b.last_seen) - +new Date(a.last_seen))
  const withFlag = items.map(a => ({ ...a, escalations: [...a.escalations], overtime: isOvertime(a) }))
  return page(withFlag, 1, 100)
}

export async function getAlert(id: string): Promise<Alert | null> {
  await delay(120)
  const a = (isSimId(id) ? simAlerts : ALERTS).find(x => x.alert_id === id)
  return a ? { ...a, overtime: isOvertime(a) } : null
}

/** 按 id 找到告警（sim / 静态两个池子） */
function findAlert(id: string): Alert | undefined {
  return (isSimId(id) ? simAlerts : ALERTS).find(x => x.alert_id === id)
}

export async function acknowledgeAlert(id: string, _operator: string): Promise<Alert> {
  await delay()
  const a = findAlert(id)
  if (!a) throw new Error('告警不存在')
  if (a.status !== 'active') throw new Error('状态非法：仅 active 可确认')
  a.status = 'acknowledged'; a.acknowledged_by = _operator; a.acknowledged_at = new Date().toISOString()
  if (!isSimId(id)) persist() // sim 数据仅驻留内存，刷新即重新演绎
  return { ...a }
}

export async function resolveAlert(id: string, operator: string, resolution: string): Promise<Alert> {
  await delay()
  const a = findAlert(id)
  if (!a) throw new Error('告警不存在')
  a.status = 'resolved'; a.resolved_by = operator; a.resolved_at = new Date().toISOString(); a.resolution = resolution
  // 高风险停井的井：告警解决即解除联锁恢复生产
  if (isSimId(id) && resumeWell(a.scope)) {
    a.escalations.push({ ts: new Date().toISOString(), kind: 'dedup', from_level: a.level, to_level: a.level, notified: ['值班员'], note: '高风险解除，井口恢复生产' })
  }
  if (!isSimId(id)) persist()
  return { ...a }
}

export async function listWorkOrders(q: { status?: string } = {}): Promise<Page<WorkOrder>> {
  await delay()
  let items = [...WORK_ORDERS, ...simOrders]
  if (q.status) items = items.filter(o => o.status === q.status)
  items.sort((a, b) => +new Date(b.created_at) - +new Date(a.created_at))
  // 返回新对象引用：mock 原地改对象会让 Vue computed 因引用相等而跳过更新（步骤条不跟随的根因）
  return page(items.map(o => ({ ...o, escalations: [...o.escalations] })), 1, 100)
}

/** 按 id 找到工单（sim / 静态两个池子） */
function findOrder(id: string): WorkOrder | undefined {
  return (isSimId(id) ? simOrders : WORK_ORDERS).find(x => x.order_id === id)
}

export async function assignOrder(id: string, assignee: string): Promise<WorkOrder> {
  await delay()
  const o = findOrder(id)
  if (!o) throw new Error('工单不存在')
  pushTransition(o, o.status, 'processing', `指派给 ${assignee}`)
  o.status = 'processing'; o.assignee = assignee; o.updated_at = new Date().toISOString()
  if (!isSimId(id)) persist()
  return { ...o }
}

export async function resolveOrder(id: string, resolution: string): Promise<WorkOrder> {
  await delay()
  const o = findOrder(id)
  if (!o) throw new Error('工单不存在')
  pushTransition(o, o.status, 'resolved', `处置完成：${resolution}`)
  o.status = 'resolved'; o.resolution = resolution; o.resolved_at = new Date().toISOString(); o.updated_at = o.resolved_at
  // 高风险停井的井：处置完成即解除联锁恢复生产
  if (isSimId(id) && resumeWell(o.well_id)) {
    pushTransition(o, 'resolved', 'resolved', '高风险解除，井口恢复生产')
  }
  if (!isSimId(id)) persist()
  return { ...o }
}

/** 关闭工单：回填实际原因，并自动沉淀为知识候选（自进化闭环） */
export async function closeOrder(id: string, actualCause: string, distill: boolean): Promise<{ order: WorkOrder; candidate?: KBCandidate }> {
  await delay(300)
  const o = findOrder(id)
  if (!o) throw new Error('工单不存在')
  pushTransition(o, o.status, 'closed', `关闭工单，实际原因：${actualCause}`)
  o.status = 'closed'; o.actual_cause = actualCause; o.closed_at = new Date().toISOString(); o.updated_at = o.closed_at
  // 高风险停井的井：关闭工单即解除联锁恢复生产
  if (isSimId(id) && resumeWell(o.well_id)) {
    pushTransition(o, 'closed', 'closed', '高风险解除，井口恢复生产')
  }
  let candidate: KBCandidate | undefined
  if (distill) {
    candidate = {
      candidate_id: `cand-${Math.random().toString(16).slice(2, 10)}`,
      source_type: 'workorder', source_id: o.order_id,
      title: `案例：${o.title}——${actualCause.slice(0, 18)}`,
      doc_type: '案例', source_ref: `工单 ${o.order_id}`,
      text: `工单：${o.title}\n处置：${o.resolution ?? '见处理记录'}\n实际原因：${actualCause}`,
      tags: [o.well_id, '工单沉淀'], status: 'pending', doc_id: null,
      review_note: null, reviewed_by: null, reviewed_at: null,
      created_at: new Date().toISOString(),
    }
    KB_CANDIDATES.unshift(candidate)
  }
  if (!isSimId(id)) persist()
  return { order: { ...o }, candidate }
}

/** 触发图谱重建（自进化闭环）：版本+1、状态置 building，3s 后完成 */
function touchGraphRebuild(): number {
  graphMeta.version += 1
  graphMeta.status = 'building'
  setTimeout(() => { graphMeta.status = 'done'; graphMeta.finished_at = new Date().toISOString() }, 3000)
  return graphMeta.version
}

// ---------------- 知识库 ----------------
export async function listDocuments(): Promise<Page<KBDocumentView>> { await delay(); return page(KB_DOCS, 1, 100) }

/** 更新文档：回写标题/内容并触发图谱重建（自进化闭环） */
export async function updateDocument(id: string, title: string, summary: string): Promise<{ doc: KBDocumentView; graph_version: number }> {
  await delay(300)
  const d = KB_DOCS.find(x => x.doc_id === id)
  if (!d) throw new Error('文档不存在')
  d.title = title; d.summary = summary; d.updated_at = new Date().toISOString()
  const v = touchGraphRebuild()
  persist()
  return { doc: { ...d }, graph_version: v }
}

let docSeq = 0
/** 添加文档：新建 ready 文档并作为节点挂入图谱，触发重建 */
export async function addDocument(input: { title: string; summary: string; doc_type: string; tags: string[] }): Promise<{ doc: KBDocumentView; graph_version: number }> {
  await delay(300)
  const id = `kb-u${Date.now().toString(36)}${(docSeq++).toString(36)}`
  const now = new Date().toISOString()
  const doc: KBDocumentView = {
    doc_id: id, title: input.title, doc_type: input.doc_type, source_ref: '手动上传',
    summary: input.summary, tags: input.tags, status: 'ready',
    chunk_count: Math.max(1, Math.round(input.summary.length / 40)), error: null,
    created_at: now, updated_at: now,
  }
  KB_DOCS.unshift(doc)
  // 图谱联动：挂文档节点 + 关联首个标签为概念节点
  GRAPH_NODES.unshift({ name: input.title, entity_type: '文档', description: input.tags.join('、') || '手动上传', sources: [id], degree: 1 })
  const tag = input.tags[0]
  if (tag && !GRAPH_NODES.some(n => n.name === tag)) {
    GRAPH_NODES.unshift({ name: tag, entity_type: '概念', description: '文档标签', sources: [id], degree: 1 })
  }
  if (tag) GRAPH_EDGES.unshift({ source: input.title, target: tag, relation: '涉及', weight: 1 })
  const v = touchGraphRebuild()
  persist()
  return { doc: { ...doc }, graph_version: v }
}

/** 删除文档：移除文档及其图谱节点与相关边，触发重建 */
export async function deleteDocument(id: string): Promise<{ graph_version: number }> {
  await delay(300)
  const i = KB_DOCS.findIndex(x => x.doc_id === id)
  if (i < 0) throw new Error('文档不存在')
  const [doc] = KB_DOCS.splice(i, 1)
  // 图谱联动：摘除文档节点及其关联边（其余节点保留，孤岛可后续清理）
  for (let k = GRAPH_NODES.length - 1; k >= 0; k--) {
    if (GRAPH_NODES[k].name === doc.title && GRAPH_NODES[k].entity_type === '文档') GRAPH_NODES.splice(k, 1)
  }
  for (let k = GRAPH_EDGES.length - 1; k >= 0; k--) {
    if (GRAPH_EDGES[k].source === doc.title || GRAPH_EDGES[k].target === doc.title) GRAPH_EDGES.splice(k, 1)
  }
  const v = touchGraphRebuild()
  persist()
  return { graph_version: v }
}

export async function listCandidates(status?: string): Promise<Page<KBCandidate>> {
  await delay()
  const items = status ? KB_CANDIDATES.filter(c => c.status === status) : [...KB_CANDIDATES]
  return page(items, 1, 100)
}

export async function approveCandidate(id: string): Promise<{ candidate: KBCandidate; graph_version: number }> {
  await delay(350)
  const c = KB_CANDIDATES.find(x => x.candidate_id === id)
  if (!c) throw new Error('候选不存在')
  c.status = 'approved'; c.reviewed_by = '值班员'; c.reviewed_at = new Date().toISOString()
  graphMeta.version += 1
  graphMeta.status = 'building'
  persist()
  // 模拟后台重建 3s 完成
  setTimeout(() => {
    graphMeta.status = 'done'
    graphMeta.node_count += 2; graphMeta.edge_count += 1
    graphMeta.finished_at = new Date().toISOString()
  }, 3000)
  return { candidate: { ...c }, graph_version: graphMeta.version }
}

export async function rejectCandidate(id: string, note: string): Promise<KBCandidate> {
  await delay()
  const c = KB_CANDIDATES.find(x => x.candidate_id === id)
  if (!c) throw new Error('候选不存在')
  c.status = 'rejected'; c.review_note = note; c.reviewed_by = '值班员'; c.reviewed_at = new Date().toISOString()
  persist()
  return { ...c }
}

export async function searchKnowledge(query: string, topK = 5): Promise<{ hits: SearchHit[]; elapsed_ms: number }> {
  const t0 = performance.now()
  await delay(260)
  const keys = query.split(/[\s，,。？?]+/).filter(Boolean)
  const hits: SearchHit[] = []
  for (const d of KB_DOCS.filter(d => d.status === 'ready')) {
    let score = 0
    for (const k of keys) {
      if (d.title.includes(k)) score += 3
      if (d.summary.includes(k)) score += 2
      if (d.tags.some(t => t.includes(k))) score += 2
    }
    if (score > 0) {
      hits.push({
        id: d.doc_id, chunk_id: `chk-${d.doc_id}-1`, source_ref: d.source_ref,
        type: d.doc_type, title: d.title, text: d.summary, tags: d.tags, score,
      })
    }
  }
  hits.sort((a, b) => b.score - a.score)
  return { hits: hits.slice(0, topK), elapsed_ms: Math.round(performance.now() - t0) }
}

// ---------------- 图谱 ----------------
const graphMeta = {
  status: 'done' as GraphStats['status'], version: 3, node_count: GRAPH_NODES.length,
  edge_count: GRAPH_EDGES.length, community_count: GRAPH_COMMUNITIES.length,
  finished_at: new Date(Date.now() - 3600_000).toISOString(),
}

export async function graphStats(): Promise<GraphStats> {
  await delay(120)
  return { ...graphMeta, built_at: graphMeta.finished_at }
}

export async function graphData(): Promise<{ nodes: GraphNode[]; edges: typeof GRAPH_EDGES; communities: GraphCommunity[] }> {
  await delay(200)
  return { nodes: GRAPH_NODES, edges: GRAPH_EDGES, communities: GRAPH_COMMUNITIES }
}

export async function entityNeighbors(name: string): Promise<{ entity: GraphNode; neighbors: NeighborItem[] }> {
  await delay(120)
  const entity = GRAPH_NODES.find(n => n.name === name)
  if (!entity) throw new Error('实体不存在')
  const neighbors: NeighborItem[] = []
  for (const e of GRAPH_EDGES) {
    if (e.source === name) {
      const node = GRAPH_NODES.find(n => n.name === e.target)
      if (node) neighbors.push({ node, relation: e.relation, direction: 'out', weight: e.weight })
    } else if (e.target === name) {
      const node = GRAPH_NODES.find(n => n.name === e.source)
      if (node) neighbors.push({ node, relation: e.relation, direction: 'in', weight: e.weight })
    }
  }
  neighbors.sort((a, b) => b.weight - a.weight)
  return { entity, neighbors }
}

export async function rebuildGraph(): Promise<{ status: string; version: number }> {
  await delay()
  graphMeta.version += 1; graphMeta.status = 'building'
  persist()
  setTimeout(() => { graphMeta.status = 'done'; graphMeta.finished_at = new Date().toISOString() }, 3000)
  return { status: 'building', version: graphMeta.version }
}

// 模块加载最后执行：用 localStorage 中的持久态覆盖初始 mock（状态机分状态存储，刷新不丢）
hydrate()
