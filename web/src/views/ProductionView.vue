<template>
  <div class="production-view">
    <!-- ============ 左：井列表（按告警等级排序） ============ -->
    <aside class="well-list">
      <el-input v-model="wellKeyword" placeholder="搜索井号 / 名称" clearable :prefix-icon="Search" class="well-search" />
      <div class="well-scroll">
        <div
          v-for="w in filteredWells" :key="w.well_id"
          class="well-item" :class="{ on: w.well_id === currentWell }"
          @click="selectWell(w.well_id)"
        >
          <span class="status-dot" :style="{ background: wellDotColor(w.well_id) }" />
          <div class="well-main">
            <div class="well-name"><span class="mono">{{ w.well_id }}</span> {{ w.name }}</div>
            <div class="well-sub">{{ w.well_type_cn }} · {{ w.location }}</div>
          </div>
          <span v-if="pausedIds.has(w.well_id)" class="paused-tag">停井</span>
          <LevelTag v-if="wellMaxLevel[w.well_id]" :level="wellMaxLevel[w.well_id]!" size="small" />
        </div>
      </div>
    </aside>

    <!-- ============ 右：曲线区 ============ -->
    <section class="chart-area">
      <div class="chart-head">
        <div class="metric-chips">
          <span
            v-for="m in wellMetrics" :key="m.suffix"
            class="metric-chip mono" :class="{ on: activeMetrics.has(m.suffix) }"
            @click="toggleMetric(m.suffix)"
          >{{ m.metric }}<i class="unit">{{ m.unit }}</i></span>
        </div>
        <!-- 数据时钟：mock=实时模拟；真实后端=后端 sim 当日序列 -->
        <span class="sim-clock mono" :title="USE_MOCK ? '实时模拟中：数据为模拟生成，刷新页面即从当前时刻重新演绎' : '真实后端 SCADA：小时整点序列 + 当前实时点，随墙钟推进，10s 自动刷新'">
          <i class="sim-dot" />{{ USE_MOCK ? '模拟' : '实时' }} {{ simClockText }}
        </span>
        <span class="mono chart-hint">{{ USE_MOCK ? '滑动窗口 5h · 2min 采样 · 实时滚动' : '今日 00:00 至现在 · 整点 + 实时点 · 10s 自动刷新' }}</span>
      </div>

      <div ref="chartRef" class="chart-box" />

      <!-- 检修日历：横向时间轴，点击联动曲线缩放 -->
      <div class="calendar-bar panel-card">
        <span class="cal-title">检修日历</span>
        <div class="cal-items">
          <span
            v-for="(ev, i) in wellEvents" :key="i"
            class="cal-chip clickable" :class="`cal-${ev.event_type}`"
            :title="ev.desc"
            @click="zoomTo(ev)"
          >
            <b>{{ ev.event_type }}</b>
            <span class="mono">{{ ev.start }}–{{ ev.end }}</span>
            <span class="cal-desc">{{ ev.desc }}</span>
          </span>
          <span v-if="!wellEvents.length" class="cal-empty">今日无检修 / 停电 / 限产事件</span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import LevelTag from '@/components/LevelTag.vue'
import { eventCalendar, getTelemetry, getTelemetryNow, listAlerts, USE_MOCK } from '@/api'
import { getPausedWellIds, getPauseMark, getScenarioFor, getSimNow } from '@/api/mock/realtime'
import { METRICS, WELLS } from '@/api/mock/data'
import type { CalendarEventView, Level, TelemetryResult } from '@/api/types'

const route = useRoute()

/** 当前基准时刻：mock 用模拟时钟，真实后端用真实时间（后端 sim 场景相对今天生成） */
function nowMs(): number { return USE_MOCK ? getSimNow() : Date.now() }

/* ---------- 时钟 badge ---------- */
const simClockText = ref('')
function refreshSimClock() {
  const d = new Date(nowMs())
  const p = (n: number) => n.toString().padStart(2, '0')
  simClockText.value = `${p(d.getHours())}:${p(d.getMinutes())}`
}

/* ---------- 井列表：搜索 + 按活动告警最高等级排序 + 停井标识 ---------- */
const wellKeyword = ref('')
const currentWell = ref('')
const wellMaxLevel = reactive<Record<string, Level | undefined>>({})
const pausedIds = ref<Set<string>>(new Set())
const LEVEL_WEIGHT: Record<Level, number> = { 紧急: 4, 预警: 3, 提醒: 2, 提示: 1 }

async function loadWellLevels() {
  const r = await listAlerts({ status: 'active' })
  for (const a of r.items) {
    const cur = wellMaxLevel[a.scope]
    if (!cur || LEVEL_WEIGHT[a.level] > LEVEL_WEIGHT[cur]) wellMaxLevel[a.scope] = a.level
  }
  pausedIds.value = USE_MOCK ? new Set(getPausedWellIds()) : new Set()
}

const filteredWells = computed(() => {
  const k = wellKeyword.value.trim()
  const list = k ? WELLS.filter(w => w.well_id.includes(k) || w.name.includes(k)) : [...WELLS]
  // 有告警的井排前面，同级按等级权重
  return list.sort((a, b) =>
    (LEVEL_WEIGHT[wellMaxLevel[b.well_id] ?? '提示'] * (wellMaxLevel[b.well_id] ? 10 : 0)) -
    (LEVEL_WEIGHT[wellMaxLevel[a.well_id] ?? '提示'] * (wellMaxLevel[a.well_id] ? 10 : 0)),
  )
})

function wellDotColor(wellId: string): string {
  if (pausedIds.value.has(wellId)) return '#6e7681' // 停井：灰点
  const lv = wellMaxLevel[wellId]
  return lv === '紧急' ? 'var(--level-critical)' : lv === '预警' ? 'var(--level-warning)'
    : lv ? 'var(--level-info)' : 'var(--level-ok)'
}

/* ---------- 指标选择（按井型过滤，多选叠加） ---------- */
const wellMetrics = computed(() => {
  const w = WELLS.find(x => x.well_id === currentWell.value)
  return METRICS.filter(m => m.wellType === w?.well_type)
})
const activeMetrics = reactive(new Set<string>())

function toggleMetric(suffix: string) {
  activeMetrics.has(suffix) ? activeMetrics.delete(suffix) : activeMetrics.add(suffix)
  renderChart()
}

function selectWell(wellId: string) {
  currentWell.value = wellId
  // 换井：默认勾选该井型第一个指标
  activeMetrics.clear()
  const first = wellMetrics.value[0]
  if (first) activeMetrics.add(first.suffix)
  loadEvents()
  renderChart()
}

/* ---------- ECharts ---------- */
const chartRef = ref<HTMLElement>()
let chart: echarts.ECharts | null = null
let resizeOb: ResizeObserver | null = null

const SERIES_COLORS = ['#2f81f7', '#3fb950', '#d29922', '#bc8cff', '#f85149', '#58a6ff']

/**
 * 渲染曲线：mock 直读 realtime 滑动窗口缓冲；真实后端经 /api/v1/telemetry 拉取当日序列。
 * 附带：越限阈值参考线（markLine）+ 高风险停井区间（红色 markArea，仅 mock 实时引擎）。
 */
async function renderChart() {
  if (!chart || !currentWell.value || !activeMetrics.size) { chart?.clear(); return }
  const suffixes = [...activeMetrics]
  const results: TelemetryResult[] = USE_MOCK
    ? suffixes.map(s => getTelemetryNow(`${currentWell.value.replace('-', '')}.${s}`))
    : await Promise.all(suffixes.map(s => getTelemetry(`${currentWell.value.replace('-', '')}.${s}`)))
  if (!chart) return // await 期间组件可能已卸载

  const series: echarts.SeriesOption[] = []
  const yAxis: echarts.YAXisComponentOption[] = []

  results.forEach((r, i) => {
    const color = SERIES_COLORS[i % SERIES_COLORS.length]
    // 多指标叠加：每个指标独立 y 轴，向右偏移
    yAxis.push({
      type: 'value', name: `${r.metric}(${r.unit})`, position: i % 2 === 0 ? 'left' : 'right',
      offset: Math.floor(i / 2) * 56,
      axisLabel: { color: '#8b949e', fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 11 },
      nameTextStyle: { color, fontSize: 11 },
      splitLine: i === 0 ? { lineStyle: { color: '#21262d' } } : { show: false },
      scale: true,
    })

    // 越限阈值参考线：该指标存在异常场景时展示（仅 mock 实时引擎）
    const sc = USE_MOCK ? getScenarioFor(currentWell.value, suffixes[i]) : null
    const markLine = sc ? {
      silent: true, symbol: 'none',
      lineStyle: { color: sc.direction === 'up' ? '#d29922' : '#f85149', type: 'dashed' as const, width: 1.4 },
      label: { formatter: `阈值 ${sc.threshold}`, fontSize: 10, color: sc.direction === 'up' ? '#d29922' : '#f85149', position: 'insideEndTop' as const },
      data: [{ yAxis: sc.threshold }],
    } : undefined

    // 高风险停井区间：仅挂在第一条曲线上（红色蒙层，仅 mock 实时引擎）
    let pauseArea: echarts.SeriesOption['markArea'] | undefined
    if (USE_MOCK && i === 0) {
      const pm = getPauseMark(currentWell.value)
      if (pm) {
        const endTs = pm.end ?? fmtSimTs(nowMs())
        pauseArea = {
          silent: false,
          data: [[
            {
              name: `高风险停井 · ${pm.reason}`,
              xAxis: pm.start,
              itemStyle: { color: 'rgba(248,81,73,.12)', borderColor: 'rgba(248,81,73,.55)', borderWidth: 1, borderType: 'dashed' as const },
              label: { show: true, position: 'top' as const, color: '#f85149', fontSize: 11, formatter: '高风险停井' },
            },
            { xAxis: endTs },
          ]] as never,
        }
      }
    }

    series.push({
      name: r.metric ?? suffixes[i], type: 'line', yAxisIndex: i,
      data: r.series.map(p => [p.ts, p.value]),
      showSymbol: false, smooth: true, color,
      lineStyle: { width: 2 },
      emphasis: { focus: 'series' },
      ...(markLine ? { markLine } : {}),
      ...(pauseArea ? { markArea: pauseArea } : {}),
    })
  })

  chart.setOption({
    backgroundColor: 'transparent',
    animation: false, // 滑动窗口滚动：关动画保证 1s 刷新平滑不跳动
    grid: { left: 70, right: 70 + Math.max(0, Math.ceil(results.length / 2) - 1) * 56, top: 40, bottom: 70 },
    legend: { textStyle: { color: '#8b949e' }, top: 4 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1f262e', borderColor: '#484f58',
      textStyle: { color: '#e6edf3', fontSize: 12 },
      axisPointer: { type: 'cross', label: { backgroundColor: '#30363d' } },
      valueFormatter: (v: unknown) => (typeof v === 'number' ? v.toFixed(2) : String(v ?? '—')),
    },
    xAxis: {
      type: 'time',
      axisLabel: { color: '#8b949e', fontFamily: 'JetBrains Mono, Consolas, monospace', fontSize: 11 },
      axisLine: { lineStyle: { color: '#30363d' } },
    },
    yAxis,
    series,
    // brush 框选缩放 + 导出 PNG + 还原
    toolbox: {
      right: 8, top: 0,
      feature: {
        dataZoom: { yAxisIndex: 'none', title: { zoom: '框选缩放', back: '缩放还原' } },
        restore: { title: '还原' },
        saveAsImage: { title: '导出 PNG', backgroundColor: '#0d1117' },
      },
      iconStyle: { borderColor: '#8b949e' },
      emphasis: { iconStyle: { borderColor: '#4a94ff' } },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18, bottom: 24, borderColor: '#30363d', backgroundColor: 'transparent', fillerColor: 'rgba(47,129,247,.15)', textStyle: { color: '#6e7681' } }],
  }, { notMerge: true })
}

/** 模拟时刻 → "YYYY-MM-DD HH:mm" */
function fmtSimTs(ms: number): string {
  const d = new Date(ms)
  const p = (n: number) => n.toString().padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 从对话/告警页跳入：定位点闪烁 3 秒（effectScatter 叠加层） */
function flashLocate() {
  if (!chart) return
  const opt = chart.getOption() as { series?: Array<{ data?: Array<[string, number]> }> }
  const first = opt.series?.[0]?.data
  if (!first?.length) return
  const last = first[first.length - 1]
  chart.setOption({
    series: [...(opt.series as object[]).map((_, i) => ({})), {
      name: '定位点', type: 'effectScatter', coordinateSystem: 'cartesian2d',
      data: [last], symbolSize: 14, zlevel: 3,
      rippleEffect: { brushType: 'stroke', scale: 3 },
      itemStyle: { color: '#f85149' },
      tooltip: { show: false },
    }],
  } as never)
  // 3 秒后移除闪烁层
  setTimeout(() => {
    if (!chart) return
    const cur = chart.getOption() as { series?: object[] }
    chart.setOption({ series: (cur.series ?? []).slice(0, -1) as never })
  }, 3000)
}

/* ---------- 检修日历 ---------- */
const wellEvents = ref<CalendarEventView[]>([])
async function loadEvents() {
  const r = await eventCalendar(currentWell.value)
  wellEvents.value = r.items
}

/** 点击日历事件 → 曲线缩放到该时间窗（用基准时钟所在日期） */
function zoomTo(ev: CalendarEventView) {
  if (!chart) return
  const d = new Date(nowMs())
  const p = (n: number) => n.toString().padStart(2, '0')
  const day = `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
  chart.dispatchAction({
    type: 'dataZoom',
    startValue: `${day} ${ev.start}`,
    endValue: `${day} ${ev.end}`,
  })
}

/* ---------- 生命周期：路由 query 自动选中 + 定位闪烁 + 实时滚动刷新 ---------- */
let rtTimer: ReturnType<typeof setInterval> | null = null   // 1s：时钟 + 曲线滚动
let slowTimer: ReturnType<typeof setInterval> | null = null // 5s：井徽标 + 停井状态

onMounted(async () => {
  await loadWellLevels()
  chart = echarts.init(chartRef.value!)
  resizeOb = new ResizeObserver(() => chart?.resize())
  resizeOb.observe(chartRef.value!)

  const qWell = (route.query.well as string) || ''
  const qMetric = (route.query.metric as string) || ''
  selectWell(WELLS.some(w => w.well_id === qWell) ? qWell : 'W-3')

  if (qMetric) {
    const def = METRICS.find(m => m.metric === qMetric && wellMetrics.value.includes(m))
    if (def) { activeMetrics.clear(); activeMetrics.add(def.suffix); renderChart() }
  }
  // 带 query 跳入时闪一下最新定位点
  if (qWell || qMetric) setTimeout(flashLocate, 400)

  // 曲线刷新：mock 1s 节奏滚动（同步直读缓冲）；真实后端 10s 拉取（整点序列 + 随墙钟推进的实时点）
  refreshSimClock()
  rtTimer = setInterval(() => {
    refreshSimClock()
    renderChart()
  }, USE_MOCK ? 1000 : 10_000)
  // 井徽标 / 停井状态变化较慢，5s 刷新即可
  slowTimer = setInterval(loadWellLevels, 5000)
})

onBeforeUnmount(() => {
  if (rtTimer) clearInterval(rtTimer)
  if (slowTimer) clearInterval(slowTimer)
  resizeOb?.disconnect()
  chart?.dispose()
})


</script>

<style scoped>
.production-view { display: flex; height: 100%; min-height: 0; }

/* 左井列表 */
.well-list {
  width: 260px; flex: none; border-right: 1px solid var(--border);
  background: var(--bg-panel); display: flex; flex-direction: column; min-height: 0;
}
.well-search { padding: 10px; }
.well-scroll { flex: 1; overflow-y: auto; padding: 4px 8px 10px; }
.well-item {
  display: flex; align-items: center; gap: 8px;
  padding: 9px 10px; border-radius: var(--radius-btn); cursor: pointer;
  border: 1px solid transparent;
  transition: background .15s ease-out;
}
.well-item:hover { background: var(--bg-elevated); }
.well-item.on { background: var(--accent-dim); border-color: rgba(47,129,247,.4); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; flex: none; box-shadow: 0 0 5px currentColor; }
.well-main { flex: 1; min-width: 0; }
.well-name { font-size: 13.5px; font-weight: 600; }
.well-name .mono { color: var(--accent-hover); }
.well-sub { font-size: 11.5px; color: var(--text-disabled); }

/* 右曲线区 */
.chart-area { flex: 1; min-width: 0; display: flex; flex-direction: column; padding: 14px 16px; gap: 12px; }
.chart-head { flex: none; display: flex; align-items: center; gap: 12px; }
.metric-chips { display: flex; flex-wrap: wrap; gap: 8px; flex: 1; }
.metric-chip {
  font-size: 12.5px; padding: 3px 12px; border-radius: 14px; cursor: pointer;
  border: 1px solid var(--border-strong); color: var(--text-secondary);
  transition: all .15s ease-out;
}
.metric-chip .unit { font-style: normal; color: var(--text-disabled); margin-left: 4px; font-size: 11px; }
.metric-chip:hover { border-color: var(--accent); }
.metric-chip.on { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-hover); }
.chart-hint { color: var(--text-disabled); font-size: 11.5px; flex: none; }

/* 模拟时钟 badge */
.sim-clock {
  flex: none; display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--level-ok);
  border: 1px solid rgba(63,185,80,.4); background: rgba(63,185,80,.08);
  padding: 2px 10px; border-radius: 12px;
}
.sim-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--level-ok); box-shadow: 0 0 6px var(--level-ok);
  animation: simBlink 1.6s ease-in-out infinite;
}
@keyframes simBlink { 0%, 100% { opacity: 1 } 50% { opacity: .3 } }

/* 停井徽标 */
.paused-tag {
  flex: none; font-size: 11px; line-height: 1; padding: 3px 6px; border-radius: 4px;
  color: #fff; background: var(--level-critical); font-weight: 600;
}

.chart-box { flex: 1; min-height: 0; }

/* 检修日历 */
.calendar-bar {
  flex: none; display: flex; align-items: center; gap: 12px;
  padding: 8px 14px; overflow-x: auto;
}
.cal-title { font-size: 12.5px; font-weight: 600; color: var(--text-secondary); flex: none; }
.cal-items { display: flex; align-items: center; gap: 10px; }
.cal-chip {
  display: inline-flex; align-items: center; gap: 8px;
  font-size: 12px; padding: 3px 10px; border-radius: var(--radius-btn);
  border: 1px solid var(--border); color: var(--text-secondary); white-space: nowrap;
}
.cal-chip b { font-weight: 600; }
.cal-检修 b { color: var(--level-warning); }
.cal-停电 b { color: var(--level-critical); }
.cal-限产 b { color: var(--level-info); }
.cal-desc { color: var(--text-disabled); max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
.cal-empty { color: var(--text-disabled); font-size: 12.5px; }
</style>
