/* ============ API 门面：USE_MOCK 切换 mock 实现 / 真实后端（vite proxy → :8000） ============ */
import * as mock from './mock_impl'
import * as http from './http'

/** mock / 真实后端开关：联调模式固定 false（改 true 回退纯前端演示） */
export const USE_MOCK = false

const impl = USE_MOCK ? mock : http

/* ---------- 井场数据 ---------- */
export const listWells = impl.listWells
export const getTelemetry = impl.getTelemetry
export const eventCalendar = impl.eventCalendar

/* ---------- 对话 ---------- */
export const chat = impl.chat

/* ---------- 告警 / 工单 ---------- */
export const listAlerts = impl.listAlerts
export const getAlert = impl.getAlert
export const acknowledgeAlert = impl.acknowledgeAlert
export const resolveAlert = impl.resolveAlert
export const listWorkOrders = impl.listWorkOrders
export const assignOrder = impl.assignOrder
export const resolveOrder = impl.resolveOrder
export const closeOrder = impl.closeOrder

/** 纯函数：前后端同口径的超时判定（active 15min / 预警 60min 未确认） */
export const isOvertime = mock.isOvertime

/* ---------- 知识库 ---------- */
export const listDocuments = impl.listDocuments
export const updateDocument = impl.updateDocument
export const addDocument = impl.addDocument
export const deleteDocument = impl.deleteDocument
export const listCandidates = impl.listCandidates
export const approveCandidate = impl.approveCandidate
export const rejectCandidate = impl.rejectCandidate
export const searchKnowledge = impl.searchKnowledge

/* ---------- 图谱 ---------- */
export const graphStats = impl.graphStats
export const graphData = impl.graphData
export const entityNeighbors = impl.entityNeighbors
export const rebuildGraph = impl.rebuildGraph

/* ---------- mock 专属（实时模拟引擎；真实模式下不应调用） ---------- */
export const getTelemetryNow = mock.getTelemetryNow
