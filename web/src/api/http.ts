/* ============ 真实后端 HTTP 实现（与 mock 同签名，经 vite proxy 转发 8000） ============ */
import type {
  Alert, ApiError, CalendarEventView, ChatResponse, GraphCommunity, GraphNode, GraphStats,
  KBCandidate, KBDocumentView, Level, NeighborItem, Page, SearchHit,
  TelemetryResult, WellView, WorkOrder,
} from './types'

/** 统一请求封装：错误体映射为 Error（message 透传后端中文提示） */
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const err = (body ?? {}) as Partial<ApiError>
    throw new Error(err.message ?? `请求失败（HTTP ${res.status}）`)
  }
  return body as T
}

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, data?: unknown) =>
  request<T>(path, { method: 'POST', body: data === undefined ? undefined : JSON.stringify(data) })
const patch = <T>(path: string, data: unknown) =>
  request<T>(path, { method: 'PATCH', body: JSON.stringify(data) })
const del = (path: string) => request<undefined>(path, { method: 'DELETE' })

function qs(params: Record<string, string | number | undefined>): string {
  const usp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') usp.set(k, String(v))
  }
  const s = usp.toString()
  return s ? `?${s}` : ''
}

/** 操作人：真实后端审计字段（后续接入登录态后替换） */
const OPERATOR = '值班员'

// ---------------- 井场数据 ----------------
export async function listWells(): Promise<Page<WellView>> {
  return get(`/api/v1/wells${qs({ page: 1, page_size: 100 })}`)
}

export async function getTelemetry(tag: string, start?: string, end?: string): Promise<TelemetryResult> {
  return get(`/api/v1/telemetry${qs({ tag, start, end })}`)
}

export async function eventCalendar(wellId?: string): Promise<Page<CalendarEventView>> {
  return get(`/api/v1/events/calendar${qs({ well_id: wellId, page: 1, page_size: 100 })}`)
}

// ---------------- 对话 ----------------
export async function chat(message: string, sessionId: string): Promise<ChatResponse> {
  return post('/api/v1/chat', { message, session_id: sessionId })
}

// ---------------- 告警 / 工单 ----------------
export interface AlertQuery { status?: string; level?: Level; well_id?: string }

export async function listAlerts(q: AlertQuery = {}): Promise<Page<Alert>> {
  return get(`/api/v1/alerts${qs({ status: q.status, level: q.level, well_id: q.well_id, page: 1, page_size: 100 })}`)
}

export async function getAlert(id: string): Promise<Alert | null> {
  try {
    return await get(`/api/v1/alerts/${encodeURIComponent(id)}`)
  } catch {
    return null
  }
}

export async function acknowledgeAlert(id: string, operator: string): Promise<Alert> {
  return post(`/api/v1/alerts/${encodeURIComponent(id)}/acknowledge`, { operator })
}

export async function resolveAlert(id: string, operator: string, resolution: string): Promise<Alert> {
  return post(`/api/v1/alerts/${encodeURIComponent(id)}/resolve`, { operator, resolution })
}

export async function listWorkOrders(q: { status?: string } = {}): Promise<Page<WorkOrder>> {
  return get(`/api/v1/workorders${qs({ status: q.status, page: 1, page_size: 100 })}`)
}

export async function assignOrder(id: string, assignee: string): Promise<WorkOrder> {
  return post(`/api/v1/workorders/${encodeURIComponent(id)}/assign`, { operator: OPERATOR, assignee })
}

export async function resolveOrder(id: string, resolution: string): Promise<WorkOrder> {
  return post(`/api/v1/workorders/${encodeURIComponent(id)}/resolve`, { operator: OPERATOR, resolution })
}

/** 关闭工单：后端闭环即自动沉淀知识候选（distill 参数仅兼容旧签名） */
export async function closeOrder(id: string, actualCause: string, _distill?: boolean): Promise<{ order: WorkOrder; candidate?: KBCandidate }> {
  const order = await post<WorkOrder>(`/api/v1/workorders/${encodeURIComponent(id)}/close`, { operator: OPERATOR, actual_cause: actualCause })
  return { order }
}

// ---------------- 知识库 ----------------
export async function listDocuments(): Promise<Page<KBDocumentView>> {
  return get(`/api/v1/kb/documents${qs({ page: 1, page_size: 100 })}`)
}

/** 图谱重建并回读版本号（增删改文档/采纳候选后的联动） */
async function triggerGraphRebuild(): Promise<number> {
  const accepted = await post<{ status: string; version: number }>('/api/v1/graph/rebuild')
  return accepted.version
}

export async function updateDocument(id: string, title: string, summary: string): Promise<{ doc: KBDocumentView; graph_version: number }> {
  const doc = await patch<KBDocumentView>(`/api/v1/kb/documents/${encodeURIComponent(id)}`, { title, text: summary })
  const graph_version = await triggerGraphRebuild()
  return { doc, graph_version }
}

export async function addDocument(input: { title: string; summary: string; doc_type: string; tags: string[] }): Promise<{ doc: KBDocumentView; graph_version: number }> {
  const doc = await post<KBDocumentView>('/api/v1/kb/documents', {
    title: input.title, doc_type: input.doc_type,
    source_ref: '手动上传', text: input.summary, tags: input.tags,
  })
  const graph_version = await triggerGraphRebuild()
  return { doc, graph_version }
}

export async function deleteDocument(id: string): Promise<{ graph_version: number }> {
  await del(`/api/v1/kb/documents/${encodeURIComponent(id)}`)
  const graph_version = await triggerGraphRebuild()
  return { graph_version }
}

export async function listCandidates(status?: string): Promise<Page<KBCandidate>> {
  return get(`/api/v1/kb/candidates${qs({ status, page: 1, page_size: 100 })}`)
}

export async function approveCandidate(id: string): Promise<{ candidate: KBCandidate; graph_version: number }> {
  const r = await post<{ candidate: KBCandidate; document: KBDocumentView }>(
    `/api/v1/kb/candidates/${encodeURIComponent(id)}/approve`, { reviewer: OPERATOR })
  const meta = await get<{ version: number }>('/api/v1/graph/rebuild/status')
  return { candidate: r.candidate, graph_version: meta.version }
}

export async function rejectCandidate(id: string, note: string): Promise<KBCandidate> {
  return post(`/api/v1/kb/candidates/${encodeURIComponent(id)}/reject`, { reviewer: OPERATOR, review_note: note })
}

export async function searchKnowledge(query: string, topK = 5): Promise<{ hits: SearchHit[]; elapsed_ms: number }> {
  const t0 = performance.now()
  const hits = await post<SearchHit[]>('/api/v1/kb/search', { query, top_k: topK })
  return { hits, elapsed_ms: Math.round(performance.now() - t0) }
}

// ---------------- 图谱 ----------------
interface GraphEdgeView { source: string; target: string; relation: string; weight: number; doc_id?: string }

export async function graphStats(): Promise<GraphStats> {
  return get('/api/v1/graph/stats')
}

export async function graphData(): Promise<{ nodes: GraphNode[]; edges: GraphEdgeView[]; communities: GraphCommunity[] }> {
  return get('/api/v1/graph/data')
}

export async function entityNeighbors(name: string): Promise<{ entity: GraphNode; neighbors: NeighborItem[] }> {
  return get(`/api/v1/graph/entities/${encodeURIComponent(name)}/neighbors`)
}

export async function rebuildGraph(): Promise<{ status: string; version: number }> {
  return post('/api/v1/graph/rebuild')
}
