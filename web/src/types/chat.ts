/* ============ 对话页视图模型（仅前端使用，非后端契约） ============ */
import type { ChatResponse } from '@/api/types'

export interface ChatMsg {
  id: string
  role: 'user' | 'assistant'
  /** 用户原文 / 助手 markdown 正文 */
  content: string
  /** 生成中占位 */
  loading?: boolean
  /** 被手动停止 */
  stopped?: boolean
  /** 助手完整响应（协同面板数据源） */
  resp?: ChatResponse
  ts: number
}
