/* ============ 实时模拟引擎 v2：滑动窗口滚动 + 持续 5s 越限判定 + 高风险自动停井 ============
 * 设计要点：
 * - 模拟时钟：每真实 1s 推进 1 模拟分钟；页面加载从 t0 开始（刷新重新演绎）
 * - 滑动窗口：每井×指标维护 150 点环形缓冲（2min 采样 ≈ 5 模拟小时），
 *   tick 时右端按采样网格追加新点、左端裁剪，曲线持续滚动
 * - 合理数据：基线 + 慢/快周期波 + 确定性抖动；加载时预置整窗正常历史，进入页面即有完整曲线
 * - 越限判定：连续 5 个 tick（≈5 秒）越限才产生告警/工单；单点毛刺自动复位不误报
 * - 高风险联锁：紧急场景触发后井自动停产（曲线跳水归零 + 红色停井区间），
 *   工单处置完成（resolved/closed）后自动恢复生产
 */
import type { Alert, Level, WorkOrder } from '../types'
import { METRICS, WELLS } from './data'

/* ---------- 时钟与窗口常量 ---------- */
const t0 = Date.now()
let simNow = t0
const TICK_MS = 1000                 // 真实 1s 一个 tick
const STEP_MIN = 1                   // 每 tick 模拟 +1 分钟
const POINT_STEP_MIN = 2             // 采样步长 2 模拟分钟（2s 真实出一个点）
const WINDOW_POINTS = 150            // 滑动窗口 150 点 ≈ 5 模拟小时
const SUSTAIN_TICKS = 5              // 越限需持续 5 个 tick（≈5 秒）才告警

export function getSimNow(): number { return simNow }

/* ---------- 基线（与 engine.BASELINE 对齐） ---------- */
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

/** 静态异常（与 engine.anomalyBoost 一致，避免循环依赖就地内联：W-3/W-5/W-6 呼应静态告警） */
function legacyBoost(wellId: string, suffix: string, phase: number): number {
  if (wellId === 'W-3' && suffix === 'wellhead_pressure' && phase > 0.6) return 0.45 * (phase - 0.6)
  if (wellId === 'W-6' && suffix === 'daily_gas_prod' && phase > 0.5) return -0.8 * (phase - 0.5)
  if (wellId === 'W-5' && suffix === 'pump_efficiency' && phase > 0.4) return -0.2 * (phase - 0.4)
  return 0
}

/* ---------- 异常场景脚本（时间均为 t0 后的模拟分钟） ---------- */
interface Scenario {
  wellId: string
  suffix: string
  direction: 'up' | 'down'
  threshold: number
  startAfterMin: number      // 多少模拟分钟后开始漂移
  rampMin: number            // 漂移到峰所需模拟分钟
  peakOffset: number         // 峰值偏移（符号由 direction 决定）
  level: Level
  cause: string
  source: string
  contentTpl: string         // {value}/{threshold}/{pct} 占位
  pauseOnFire?: boolean      // 高风险：触发即停井
  spikes?: { centerMin: number; widthMin: number; offset: number }[] // 瞬时毛刺（验证防误报）
  // 运行时状态
  streak: number             // 连续越限 tick 数
  firedAtMs: number | null   // 触发时刻（触发后漂移 10 模拟分钟内衰减归零，模拟处置恢复）
}

const SCENARIOS: Scenario[] = [
  {
    wellId: 'W-1', suffix: 'current', direction: 'up', threshold: 58,
    startAfterMin: 8, rampMin: 36, peakOffset: 22,
    level: '提醒', cause: '电流持续抬升', source: 'device_diagnosis',
    contentTpl: 'W-1 上行电流当前 {value} A，阈值 {threshold} A，偏离 {pct}，疑似抽油机负载异常',
    // 两个单点毛刺：短暂越限后回落，验证"持续 5 秒才告警"不误报
    spikes: [
      { centerMin: 12, widthMin: 1, offset: 20 },
      { centerMin: 22, widthMin: 1, offset: 24 },
    ],
    streak: 0, firedAtMs: null,
  },
  {
    wellId: 'W-4', suffix: 'wob', direction: 'up', threshold: 155,
    startAfterMin: 15, rampMin: 45, peakOffset: 60,
    level: '预警', cause: '钻压持续爬升', source: 'device_diagnosis',
    contentTpl: 'W-4 钻压当前 {value} kN，阈值 {threshold} kN，偏离 {pct}，疑似钻头遇阻',
    streak: 0, firedAtMs: null,
  },
  {
    wellId: 'W-7', suffix: 'wellhead_pressure', direction: 'down', threshold: 0.95,
    startAfterMin: 25, rampMin: 40, peakOffset: 0.6,
    level: '紧急', cause: '井口压力骤降', source: 'production_analysis',
    contentTpl: 'W-7 井口压力当前 {value} MPa，跌破阈值 {threshold} MPa，偏离 {pct}，疑似井口或管线泄漏',
    pauseOnFire: true, // 高风险：触发即自动停井
    streak: 0, firedAtMs: null,
  },
]

function smoothstep(x: number): number { return x * x * (3 - 2 * x) }

/** 场景漂移 + 触发后衰减 + 瞬时毛刺 */
function scenarioDrift(wellId: string, suffix: string, atMs: number): number {
  let off = 0
  for (const s of SCENARIOS) {
    if (s.wellId !== wellId || s.suffix !== suffix) continue
    const sign = s.direction === 'up' ? 1 : -1
    const elapsedMin = (atMs - t0) / 60_000
    let d = 0
    if (elapsedMin > s.startAfterMin) {
      const x = Math.min(1, (elapsedMin - s.startAfterMin) / s.rampMin)
      d = s.peakOffset * smoothstep(x)
    }
    // 触发后 10 模拟分钟内漂移衰减归零（模拟"处置后工况恢复"）
    if (s.firedAtMs != null && atMs > s.firedAtMs) {
      d *= Math.max(0, 1 - (atMs - s.firedAtMs) / (10 * 60_000))
    }
    off += sign * d
    for (const sp of s.spikes ?? []) {
      const c = t0 + sp.centerMin * 60_000
      const tri = Math.max(0, 1 - Math.abs(atMs - c) / (sp.widthMin * 60_000))
      off += sign * sp.offset * tri
    }
  }
  return off
}

/* ---------- 停井状态（高风险联锁） ---------- */
interface PauseMark { since: number; until: number | null; reason: string }
const pauses = new Map<string, PauseMark>()

export function isPaused(wellId: string): boolean {
  const p = pauses.get(wellId)
  return !!p && p.until == null
}

export function getPausedWellIds(): string[] {
  return [...pauses.entries()].filter(([, p]) => p.until == null).map(([w]) => w)
}

/** 高风险解除：恢复生产（由 api 层在工单 resolved/closed 时调用） */
export function resumeWell(wellId: string): boolean {
  const p = pauses.get(wellId)
  if (!p || p.until != null) return false
  p.until = simNow
  return true
}

/** 图谱渲染用停井区间（end 为 null 表示仍在停） */
export function getPauseMark(wellId: string): { start: string; end: string | null; reason: string } | null {
  const p = pauses.get(wellId)
  if (!p) return null
  return { start: fmtTs(new Date(p.since)), end: p.until == null ? null : fmtTs(new Date(p.until)), reason: p.reason }
}

/** 查询某井某指标的场景阈值（画阈值参考线用） */
export function getScenarioFor(wellId: string, suffix: string): { threshold: number; direction: 'up' | 'down'; level: Level } | null {
  const s = SCENARIOS.find(x => x.wellId === wellId && x.suffix === suffix)
  return s ? { threshold: s.threshold, direction: s.direction, level: s.level } : null
}

/* ---------- 指标取值 ---------- */
function rawValue(wellId: string, suffix: string, atMs: number): number {
  const spec = BASELINE[suffix]
  const base = spec?.base ?? 10
  const amp = spec?.amp ?? 2
  const minV = spec?.min ?? 0
  const mins = atMs / 60_000
  const seed = wellId.length + Number(wellId.replace(/\D/g, ''))
  // 慢周期（小时级工况波动）+ 快周期（分钟级波动）+ 确定性抖动（可复现不跳变）
  const v = base
    + Math.sin(mins / 45 + seed) * amp * 0.9
    + Math.sin(mins / 7 + seed * 2) * amp * 0.22
    + Math.sin(mins * 12.9898 + seed * 7.233) * amp * 0.07
    + legacyBoost(wellId, suffix, mins / (24 * 60))
    + scenarioDrift(wellId, suffix, atMs)
  return Math.max(minV, v)
}

function metricValue(wellId: string, suffix: string, atMs: number): number {
  const p = pauses.get(wellId)
  if (p && p.until == null && atMs >= p.since) {
    // 停井：产量/压力类近零；温度类回落到环境温度
    if (suffix.includes('temp')) return 16 + Math.sin(atMs / 600_000) * 0.8
    const base = BASELINE[suffix]?.base ?? 10
    return Math.max(0, base * 0.02 + Math.sin(atMs / 60_000) * 0.01)
  }
  return rawValue(wellId, suffix, atMs)
}

/* ---------- 滑动窗口缓冲 ---------- */
function pad(n: number) { return n.toString().padStart(2, '0') }
function fmtTs(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const seriesBuf = new Map<string, { ts: string; value: number }[]>() // key: `W-3|wellhead_pressure`
let nextSampleMs = 0

function appendUpTo(untilMs: number) {
  while (nextSampleMs <= untilMs) {
    for (const w of WELLS) {
      for (const m of METRICS) {
        if (m.wellType !== w.well_type) continue
        const key = `${w.well_id}|${m.suffix}`
        let buf = seriesBuf.get(key)
        if (!buf) { buf = []; seriesBuf.set(key, buf) }
        buf.push({ ts: fmtTs(new Date(nextSampleMs)), value: Number(metricValue(w.well_id, m.suffix, nextSampleMs).toFixed(3)) })
        if (buf.length > WINDOW_POINTS) buf.splice(0, buf.length - WINDOW_POINTS)
      }
    }
    nextSampleMs += POINT_STEP_MIN * 60_000
  }
}

/** 按 tag 取窗口数据（tag 形如 "W3.wellhead_pressure"） */
export function getSeries(tag: string): { ts: string; value: number }[] {
  const head = tag.split('.')[0]
  const wellId = `W-${head.replace(/\D/g, '')}`
  const suffix = tag.split('.')[1] ?? ''
  return (seriesBuf.get(`${wellId}|${suffix}`) ?? []).map(p => ({ ...p }))
}

/* ---------- 越限判定与派单 ---------- */
export const simAlerts: Alert[] = []
export const simOrders: WorkOrder[] = []

let simSeq = 0
const simId = (p: string) => `sim-${p}-${(++simSeq).toString().padStart(3, '0')}`

type SimAlertListener = (alert: Alert, order: WorkOrder) => void
const listeners: SimAlertListener[] = []
export function onSimAlert(fn: SimAlertListener) { listeners.push(fn) }

function raise(s: Scenario, value: number) {
  const metric = METRICS.find(m => m.suffix === s.suffix)
  const pct = s.direction === 'up'
    ? `+${(((value - s.threshold) / s.threshold) * 100).toFixed(0)}%`
    : `-${(((s.threshold - value) / s.threshold) * 100).toFixed(0)}%`
  const tsIso = new Date(simNow).toISOString()
  let content = s.contentTpl
    .replace('{value}', String(value))
    .replace('{threshold}', String(s.threshold))
    .replace('{pct}', pct)
  content += `（越限已持续 ${SUSTAIN_TICKS} 秒）`
  if (s.pauseOnFire) content += '；已触发高风险联锁，井口自动停产'
  const alert: Alert = {
    alert_id: simId('alt'), dedup_key: `${s.wellId}|${metric?.metric ?? s.suffix}|越限`,
    level: s.level, source: s.source, cause: s.cause, scope: s.wellId,
    content,
    status: 'active', hit_count: 1, suppressed_count: 0,
    first_seen: tsIso, last_seen: tsIso,
    acknowledged_by: null, acknowledged_at: null,
    resolved_by: null, resolved_at: null, resolution: null,
    escalations: [], trace_id: simId('tr'),
  }
  const order: WorkOrder = {
    order_id: simId('ord'), alert_id: alert.alert_id,
    title: `${s.wellId} ${s.cause}处置${s.pauseOnFire ? '（高风险停井）' : ''}`,
    priority: s.level, device_id: `DEV-00${s.wellId.replace('W-', '')}`, well_id: s.wellId,
    status: 'pending', assignee: null, actions_taken: null, resolution: null, actual_cause: null,
    created_at: tsIso, updated_at: tsIso, resolved_at: null, closed_at: null,
    escalations: [],
  }
  if (s.pauseOnFire) pauses.set(s.wellId, { since: simNow, until: null, reason: s.cause })
  simAlerts.unshift(alert)
  simOrders.unshift(order)
  for (const fn of listeners) fn(alert, order)
}

/** 推进模拟时钟：追加滑动窗口新点 + 持续越限判定（连续 5s 才告警） */
export function tick() {
  simNow += STEP_MIN * 60_000
  appendUpTo(simNow)
  for (const s of SCENARIOS) {
    if (s.firedAtMs != null) continue
    const buf = seriesBuf.get(`${s.wellId}|${s.suffix}`)
    const v = buf?.[buf.length - 1]?.value ?? 0
    const violated = s.direction === 'up' ? v >= s.threshold : v <= s.threshold
    s.streak = violated ? s.streak + 1 : 0
    if (s.streak >= SUSTAIN_TICKS) { s.firedAtMs = simNow; raise(s, v) }
  }
}

/* ---------- 定时驱动 ---------- */
let timer: ReturnType<typeof setInterval> | null = null

/** 启动实时模拟：默认每真实 1s 一个 tick */
export function startRealtime(intervalMs: number = TICK_MS) {
  if (timer) return
  timer = setInterval(tick, intervalMs)
}

export function stopRealtime() {
  if (timer) { clearInterval(timer); timer = null }
}

/* ---------- 模块加载：预置整窗正常历史，进入页面即有完整曲线 ---------- */
nextSampleMs = t0 - (WINDOW_POINTS - 1) * POINT_STEP_MIN * 60_000
appendUpTo(t0)
