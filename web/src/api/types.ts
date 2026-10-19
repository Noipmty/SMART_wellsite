/* ============ API 契约类型（与 smart-wellsite 后端严格对齐） ============ */

/** 统一分页响应（libs/api Page[T]） */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages?: number
}

/** 统一错误体 */
export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown>
  request_id?: string
}

// ---------- 枚举 ----------
export type Level = '提示' | '提醒' | '预警' | '紧急'
export type ConfidenceLevel = '高' | '中' | '低'
export type AlertStatus = 'active' | 'acknowledged' | 'resolved'
export type WorkOrderStatus = 'pending' | 'processing' | 'resolved' | 'closed'
export type IndexStatus = 'pending' | 'indexing' | 'ready' | 'failed'
export type CandidateStatus = 'pending' | 'approved' | 'rejected'
export type EntityType = '井' | '风险' | '概念' | '文档'
export type BuildStatus = 'idle' | 'building' | 'done' | 'failed'

// ---------- 井场 ----------
export interface WellView {
  well_id: string
  name: string
  well_type: 'oil' | 'gas' | 'drilling'
  well_type_cn: string
  device_id: string
  device_type: string
  location: string
  status: string
}

export interface TelemetryPoint { ts: string; value: number }

export interface TelemetryResult {
  tag: string
  metric: string | null
  unit: string | null
  series: TelemetryPoint[]
  quality: { gap?: Array<{ start: string; end: string; reason?: string }> } & Record<string, unknown>
  events: unknown[]
}

export interface CalendarEventView {
  event_type: string
  wells: string[]
  start: string
  end: string
  desc: string
}

// ---------- 对话 ----------
export interface ChatRequest {
  message: string
  session_id?: string
  context?: Record<string, unknown>
}

export interface Evidence {
  ts?: string | null
  metric: string
  value?: number | string | null
  trend?: string | null
  source?: string | null
  detail?: string | null
}

export interface ParameterAdvice {
  param: string
  from?: number | string | null
  to?: number | string | null
  reason: string
  confirm_required: boolean
  observe_hours?: number | null
}

export interface AgentResultView {
  agent: string
  conclusion: string
  confidence: number
  confidence_level: ConfidenceLevel | null
  evidence: Evidence[]
  suggestion: string | null
  parameter_advice: ParameterAdvice[]
  needs_review: boolean
  partial: boolean
  error: string | null
  elapsed_ms: number | null
  citations: string[]
  data: Record<string, unknown>
}

export interface ChatResponse {
  reply: string
  session_id: string
  trace_id: string
  citations: string[]
  confidence_level: ConfidenceLevel | null
  need_clarify: boolean
  clarify_options: string[]
  conflicts: string[]
  partial: boolean
  tools_called: string[]
  results: AgentResultView[]
  timestamp: string
}

// ---------- 告警 / 工单 ----------
export interface EscalationRecord {
  ts: string
  kind: string // dedup / timeout
  from_level: string
  to_level: string
  notified: string[]
  note: string
}

export interface Alert {
  alert_id: string
  dedup_key: string
  level: Level
  source: string
  cause: string
  scope: string
  content: string
  status: AlertStatus
  hit_count: number
  suppressed_count: number
  first_seen: string
  last_seen: string
  acknowledged_by: string | null
  acknowledged_at: string | null
  resolved_by: string | null
  resolved_at: string | null
  resolution: string | null
  escalations: EscalationRecord[]
  trace_id: string
  /** 前端计算字段：是否超时未处置 */
  overtime?: boolean
}

export interface WorkOrder {
  order_id: string
  alert_id: string
  title: string
  priority: string
  device_id: string
  well_id: string
  status: WorkOrderStatus
  assignee: string | null
  actions_taken: string | null
  resolution: string | null
  actual_cause: string | null
  created_at: string
  updated_at: string
  resolved_at: string | null
  closed_at: string | null
  escalations: EscalationRecord[]
}

// ---------- 知识库 ----------
export interface KBDocumentView {
  doc_id: string
  title: string
  doc_type: string
  source_ref: string
  summary: string
  tags: string[]
  status: IndexStatus
  chunk_count: number
  error: string | null
  created_at: string
  updated_at: string
}

export interface KBChunk {
  chunk_id: string
  doc_id: string
  seq: number
  text: string
  tags: string[]
  created_at: string
}

export interface KBCandidate {
  candidate_id: string
  source_type: 'workorder' | 'alert_dedup' | 'trace'
  source_id: string
  title: string
  doc_type: string
  source_ref: string
  text: string
  tags: string[]
  status: CandidateStatus
  doc_id: string | null
  review_note: string | null
  reviewed_by: string | null
  reviewed_at: string | null
  created_at: string
}

export interface SearchHit {
  id: string
  chunk_id: string
  source_ref: string
  type: string
  title: string
  text: string
  tags: string[]
  score: number
}

// ---------- 图谱 ----------
export interface GraphNode {
  name: string
  entity_type: EntityType
  description: string
  sources: string[]
  degree: number
}

export interface GraphCommunity {
  community_id: string
  title: string
  summary: string
  members: string[]
  size: number
}

export interface GraphStats {
  status: BuildStatus
  version: number
  node_count: number
  edge_count: number
  community_count: number
  built_at: string | null
}

export interface NeighborItem {
  node: GraphNode
  relation: string
  direction: string
  weight: number
}

// ---------- 链路追踪 ----------
export interface TraceSummary {
  trace_id: string
  session_id: string | null
  question: string
  intent: string
  need_clarify: boolean
  agents: string[]
  conflicts: string[]
  partial: boolean
  duration_ms: number
  created_at: string
  result_count: number
}

export interface TraceRecord extends Omit<TraceSummary, 'result_count'> {
  results: AgentResultView[]
}
