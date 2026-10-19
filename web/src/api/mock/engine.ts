/* ============ Mock 引擎：对话编排模拟（对齐 orchestrator；时序已迁 realtime 滑动窗口） ============ */
import type {
  AgentResultView, ChatResponse, ConfidenceLevel, Evidence, TelemetryResult,
} from '../types'
import { ALERTS, METRICS, WELLS } from './data'

let seed = 42
/** 简单可复现伪随机 */
function rand() {
  seed = (seed * 1103515245 + 12345) % 2147483648
  return seed / 2147483648
}

function pad(n: number) { return n.toString().padStart(2, '0') }
function fmtTs(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** 指标基线（模拟各井指标正常区间） */
const BASELINE: Record<string, { base: number; amp: number; min: number }> = {
  daily_oil_prod: { base: 12.5, amp: 1.5, min: 8 },
  pump_efficiency: { base: 0.62, amp: 0.05, min: 0.4 },
  submergence: { base: 320, amp: 30, min: 200 },
  current: { base: 45, amp: 6, min: 25 },
  casing_pressure: { base: 1.1, amp: 0.2, min: 0.4 },
  stroke_freq: { base: 5.2, amp: 0.4, min: 3 },
  daily_gas_prod: { base: 3.2, amp: 0.4, min: 1.8 },
  wellhead_pressure: { base: 1.3, amp: 0.15, min: 0.8 },
  throttle_in_pressure: { base: 3.6, amp: 0.3, min: 2.5 },
  wellhead_temp: { base: 38, amp: 4, min: 20 },
  wob: { base: 120, amp: 20, min: 60 },
  rpm: { base: 110, amp: 10, min: 70 },
  mud_density: { base: 1.2, amp: 0.03, min: 1.1 },
}

/** W-3 井口压力异常抬升（与告警 mock 呼应） */
function anomalyBoost(wellId: string, suffix: string, t: number): number {
  if (wellId === 'W-3' && suffix === 'wellhead_pressure' && t > 0.6) return 0.45 * (t - 0.6)
  if (wellId === 'W-6' && suffix === 'daily_gas_prod' && t > 0.5) return -0.8 * (t - 0.5)
  if (wellId === 'W-5' && suffix === 'pump_efficiency' && t > 0.4) return -0.2 * (t - 0.4)
  return 0
}

/** 生成时序：以模拟时钟为末端回看 24h，30min 步长；W-3 12:00–14:00 检修缺口保留 */
export function genTelemetry(tag: string, start?: string, end?: string): TelemetryResult {
  const [head, suffix] = tag.split('.')
  const wellId = `W-${head.replace(/\D/g, '')}`
  const metric = METRICS.find(m => m.suffix === suffix)
  const spec = BASELINE[suffix] ?? { base: 10, amp: 2, min: 0 }

  // 默认窗口：当天 00:00–23:59（时序展示已迁 realtime 滑动窗口，此函数仅兜底保留）
  const nowMs = Date.now()
  const e = end ? new Date(end.replace(' ', 'T')) : new Date(nowMs)
  const s = start ? new Date(start.replace(' ', 'T')) : new Date(nowMs - 24 * 3600_000)
  const span = e.getTime() - s.getTime()

  const gap = wellId === 'W-3'
    ? [{ start: fmtTs(new Date(s.getFullYear(), s.getMonth(), s.getDate(), 12, 0)), end: fmtTs(new Date(s.getFullYear(), s.getMonth(), s.getDate(), 14, 0)), reason: '计划检修（井口针阀拆检）' }]
    : []

  const series = []
  const step = 30 * 60_000
  for (let t = s.getTime(); t <= e.getTime(); t += step) {
    const d = new Date(t)
    const hhmm = `${pad(d.getHours())}:${pad(d.getMinutes())}`
    if (gap.length && hhmm >= gap[0].start.slice(11) && hhmm < gap[0].end.slice(11)) continue // 缺口段不出点
    const phase = (t - s.getTime()) / span
    const v = spec.base
      + spec.amp * Math.sin(phase * Math.PI * 2 + head.length)
      + (rand() - 0.5) * spec.amp * 0.4
      + anomalyBoost(wellId, suffix, phase)
    series.push({ ts: fmtTs(d), value: Math.max(spec.min, Number(v.toFixed(3))) })
  }
  return { tag, metric: metric?.metric ?? suffix, unit: metric?.unit ?? '', series, quality: { gap }, events: [] }
}

// ---------------- 对话编排模拟 ----------------

const AGENT_CN: Record<string, string> = {
  data_collector: '数据采控', device_diagnosis: '设备诊断', production_analysis: '生产分析',
  safety_risk: '安全风险', alert_handler: '告警处置', report_knowledge: '报表知识',
  video_intelligence: '视频智能', environment_safety: '环境安全',
}

export function agentCn(agent: string): string { return AGENT_CN[agent] ?? agent }

function ev(metric: string, value: number | string, detail?: string, trend?: string): Evidence {
  return { metric, value, detail: detail ?? null, trend: trend ?? null, source: 'sim-scada' }
}

function mkResult(agent: string, conclusion: string, confidence: number, evidence: Evidence[], ms: number, extra?: Partial<AgentResultView>): AgentResultView {
  const level: ConfidenceLevel = confidence >= 0.8 ? '高' : confidence >= 0.6 ? '中' : '低'
  return {
    agent, conclusion, confidence, confidence_level: level, evidence,
    suggestion: null, parameter_advice: [], needs_review: false, partial: false,
    error: null, elapsed_ms: ms, citations: [], data: {}, ...extra,
  }
}

function uid(p: string) { return `${p}-${Math.random().toString(16).slice(2, 10)}` }

/** 识别消息中的井号 */
export function extractWell(message: string): string | null {
  const m = message.match(/[WwJj][-_ ]?(\d+)/) ?? message.match(/(\d+)\s*号井?/)
  if (!m) return null
  const wid = `W-${m[1]}`
  return WELLS.some(w => w.well_id === wid) ? wid : null
}

/** mock /api/v1/chat：按关键词走不同编排场景 */
export function mockChat(message: string, sessionId: string): ChatResponse {
  const traceId = uid('tr')
  const well = extractWell(message)
  const base: Omit<ChatResponse, 'reply' | 'results'> = {
    session_id: sessionId, trace_id: traceId, citations: [], confidence_level: '高',
    need_clarify: false, clarify_options: [], conflicts: [], partial: false,
    tools_called: [], timestamp: new Date().toISOString(),
  }

  // 场景 1：指标口径歧义 → 澄清
  if (message.includes('产量') && well && WELLS.find(w => w.well_id === well)?.well_type === 'oil' && !message.includes('井口') && !message.includes('净化')) {
    return {
      ...base, reply: `您查询的是 ${well} 的产量。该井存在两个产量口径，请确认口径后我再为您取数：`,
      confidence_level: null, need_clarify: true,
      clarify_options: ['井口日产量', '净化日产量', `切换到 ${well === 'W-3' ? 'W-5' : 'W-3'}`, '查看该井今日告警'],
      results: [],
    }
  }

  // 场景 2：无井号的泛化问题 → 异常井汇总
  if (message.includes('异常') || message.includes('今天') || message.includes('哪些')) {
    const actives = ALERTS.filter(a => a.status === 'active')
    const lines = actives.map(a => `- **[${a.level}] ${a.scope}** ${a.cause}（hit ${a.hit_count}）`).join('\n')
    return {
      ...base,
      reply: `今日井场共 **${actives.length} 条活动告警**，涉及 ${new Set(actives.map(a => a.scope)).size} 口井：\n\n${lines}\n\n建议优先处置 **W-3 井口压力超限**（紧急，已连续 3 次命中并自动升级）。`,
      citations: ['告警 alt-a31f09c2', '告警 alt-77bd41e5'],
      tools_called: ['data_collector', 'alert_handler'],
      results: [
        mkResult('data_collector', '已汇总 7 口井实时状态与活动告警', 0.95, [ev('活动告警数', actives.length), ev('在线井数', 7)], 180),
        mkResult('alert_handler', 'W-3 井口压力超限已升级为紧急并生成工单 ord-1024', 0.9,
          [ev('井口压力', '1.82 MPa'), ev('阈值', '1.50 MPa'), ev('偏离', '+21%')], 220,
          { data: { alert_id: 'alt-a31f09c2', order_id: 'ord-1024', level: '紧急' } }),
      ],
    }
  }

  // 场景 3：趋势查询
  if ((message.includes('趋势') || message.includes('压力') || message.includes('最近')) && well) {
    return {
      ...base,
      reply: `**${well} 井口压力近 24h 趋势分析**：\n\n1. 08:00 前压力稳定在 1.2–1.4 MPa 区间；\n2. 08:00 后持续抬升，当前 **1.82 MPa**，超阈值（1.50 MPa）**+21%**；\n3. 12:00–14:00 为计划检修窗口（井口针阀拆检），该时段数据缺失。\n\n趋势仍在缓慢上行，建议核查外输管线回压是否升高，可在生产数据页查看完整曲线。`,
      citations: ['W3.wellhead_pressure', '事件日历：W-3 检修'],
      confidence_level: '高',
      tools_called: ['data_collector', 'production_analysis'],
      results: [
        mkResult('data_collector', `已拉取 ${well} 井口压力 24h 时序（48 点，1 个缺口）`, 0.98,
          [ev('采样点', 48), ev('缺口', '12:00–14:00', '计划检修')], 150),
        mkResult('production_analysis', '井口压力 8h 抬升 +38%，超阈值 +21%，判定异常上行', 0.87,
          [ev('井口压力', '1.82 MPa', undefined, '上升'), ev('阈值', '1.50 MPa'), ev('偏离', '+21%')], 460,
          {
            suggestion: '核查外输管线回压，必要时降冲次观察',
            parameter_advice: [{ param: '冲次', from: 5.2, to: 4.5, reason: '降载观察压力响应', confirm_required: true, observe_hours: 2 }],
          }),
      ],
    }
  }

  // 场景 4：原因诊断
  if ((message.includes('为什么') || message.includes('原因') || message.includes('下降')) && well) {
    return {
      ...base,
      reply: `**${well} 产量下降诊断**：\n\n- 日产气量 24h 下降 **-18%**，井口温度同步降至 **12.4℃**；\n- 节流前后压差增大 0.6 MPa；\n- 结合近期降温，**疑似节流阀冰堵**（置信度 87%）。\n\n**建议**：投运伴热带并观察 2h，若产量未恢复再排查水合物段塞。`,
      citations: ['W6.daily_gas_prod', '文档: 采气井冬季防冻堵操作规程'],
      tools_called: ['data_collector', 'device_diagnosis', 'report_knowledge'],
      results: [
        mkResult('data_collector', '已拉取产量/温度/压差三组时序', 0.97, [ev('日产气量', '2.6×10⁴m³/d', undefined, '下降'), ev('井口温度', '12.4℃')], 160),
        mkResult('device_diagnosis', '节流阀冰堵可能性最高（87%），水合物段塞次之（9%）', 0.87,
          [ev('日产气量', '-18%'), ev('节流压差', '+0.6 MPa'), ev('井口温度', '12.4℃')], 820,
          { suggestion: '投运伴热带，观察 2 小时', citations: ['kb-9d02'] }),
        mkResult('report_knowledge', '命中规程《采气井冬季防冻堵操作规程》相关条款 2 条', 0.92,
          [ev('命中分块', 2)], 240, { citations: ['kb-9d02'] }),
      ],
    }
  }

  // 场景 5：知识问答
  if (message.includes('怎么') || message.includes('如何') || message.includes('处置') || message.includes('规程')) {
    return {
      ...base,
      reply: `根据《井口压力超限应急处置预案》（YA-WX-2024-003）：\n\n1. **核查外输管线回压**，确认是否下游憋压；\n2. **检查针阀开度**，排除节流异常；\n3. 必要时**降冲次运行**并连续观察 30 分钟；\n4. 压力超阈值 15% 以上须 **30 分钟内上报班长**。\n\n当前 W-3 已命中该预案第 4 条，工单 ord-1024 处置中。`,
      citations: ['文档: 井口压力超限应急处置预案 p.1', '工单 ord-1024'],
      tools_called: ['report_knowledge'],
      results: [
        mkResult('report_knowledge', '检索命中预案 1 篇、案例 1 篇，综合置信度高', 0.9,
          [ev('命中文档', '井口压力超限应急处置预案'), ev('score', 8)], 310,
          { citations: ['kb-9d03'] }),
      ],
    }
  }

  // 兜底
  return {
    ...base,
    reply: `我已理解您的问题。当前 mock 环境支持以下问法：\n\n- 「今天有哪些异常井？」\n- 「W-3 最近24小时井口压力趋势」\n- 「W-6 日产气量为什么下降？」\n- 「井口压力超限应该怎么处置？」\n\n您也可以点击井号（如 W-3）直接跳转生产数据页。`,
    confidence_level: '中', partial: false,
    results: [mkResult('report_knowledge', '未匹配到明确意图，返回引导话术', 0.5, [], 60)],
  }
}
