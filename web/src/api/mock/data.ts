/* ============ Mock 数据源（对齐后端 sim/ 与 schemas） ============ */
import type {
  Alert, CalendarEventView, GraphCommunity, GraphNode, KBCandidate,
  KBDocumentView, Level, WellView, WorkOrder,
} from '../types'

export const SITE_ID = 'WS001'

/** 井号台账（与 sim/registry.py 一致） */
export const WELLS: WellView[] = [
  { well_id: 'W-1', name: '1号采油井', well_type: 'oil', well_type_cn: '采油', device_id: 'DEV-001', device_type: 'pumping_unit', location: '东区 A 排', status: 'active' },
  { well_id: 'W-2', name: '2号采气井', well_type: 'gas', well_type_cn: '采气', device_id: 'DEV-002', device_type: 'gas_wellhead', location: '东区 B 排', status: 'active' },
  { well_id: 'W-3', name: '3号采油井', well_type: 'oil', well_type_cn: '采油', device_id: 'DEV-003', device_type: 'pumping_unit', location: '中区 C 排', status: 'active' },
  { well_id: 'W-4', name: '4号钻井', well_type: 'drilling', well_type_cn: '钻井', device_id: 'DEV-004', device_type: 'drilling_rig', location: '南区钻井平台', status: 'active' },
  { well_id: 'W-5', name: '5号采油井', well_type: 'oil', well_type_cn: '采油', device_id: 'DEV-005', device_type: 'pumping_unit', location: '西区 D 排', status: 'active' },
  { well_id: 'W-6', name: '6号采气井', well_type: 'gas', well_type_cn: '采气', device_id: 'DEV-006', device_type: 'gas_wellhead', location: '西区 E 排', status: 'active' },
  { well_id: 'W-7', name: '7号采气井', well_type: 'gas', well_type_cn: '采气', device_id: 'DEV-007', device_type: 'gas_wellhead', location: '北区 F 排', status: 'active' },
]

/** 点表（与 sim/points.py 一致，前端展示用子集） */
export interface MetricDef { metric: string; suffix: string; unit: string; wellType: string }
export const METRICS: MetricDef[] = [
  { metric: '井口日产量', suffix: 'daily_oil_prod', unit: 't/d', wellType: 'oil' },
  { metric: '泵效', suffix: 'pump_efficiency', unit: '1', wellType: 'oil' },
  { metric: '沉没度', suffix: 'submergence', unit: 'm', wellType: 'oil' },
  { metric: '电流', suffix: 'current', unit: 'A', wellType: 'oil' },
  { metric: '套压', suffix: 'casing_pressure', unit: 'MPa', wellType: 'oil' },
  { metric: '冲次', suffix: 'stroke_freq', unit: '次/min', wellType: 'oil' },
  { metric: '日产气量', suffix: 'daily_gas_prod', unit: '10⁴m³/d', wellType: 'gas' },
  { metric: '井口压力', suffix: 'wellhead_pressure', unit: 'MPa', wellType: 'gas' },
  { metric: '节流前压力', suffix: 'throttle_in_pressure', unit: 'MPa', wellType: 'gas' },
  { metric: '井口温度', suffix: 'wellhead_temp', unit: '℃', wellType: 'gas' },
  { metric: '钻压', suffix: 'wob', unit: 'kN', wellType: 'drilling' },
  { metric: '转速', suffix: 'rpm', unit: 'r/min', wellType: 'drilling' },
  { metric: '泥浆密度', suffix: 'mud_density', unit: 'g/cm³', wellType: 'drilling' },
]

const now = Date.now()
const min = (m: number) => new Date(now - m * 60_000).toISOString()

/** 告警（含 hit 去重、抑制、升级记录、超时场景） */
export const ALERTS: Alert[] = [
  {
    alert_id: 'alt-a31f09c2', dedup_key: 'W-3|井口压力|超限', level: '紧急', source: 'device_diagnosis',
    cause: '井口压力超限', scope: 'W-3', content: 'W-3 井口压力 1.82 MPa，阈值 1.50 MPa，偏离 +21%，连续 3 次命中',
    status: 'active', hit_count: 3, suppressed_count: 5,
    first_seen: min(95), last_seen: min(12),
    acknowledged_by: null, acknowledged_at: null, resolved_by: null, resolved_at: null, resolution: null,
    escalations: [
      { ts: min(60), kind: 'dedup', from_level: '预警', to_level: '紧急', notified: ['值班员', '班长'], note: '去重窗口内命中 3 次，自动升级' },
    ],
    trace_id: 'tr-88f2c1a0',
  },
  {
    alert_id: 'alt-77bd41e5', dedup_key: 'W-5|泵效|下降', level: '预警', source: 'production_analysis',
    cause: '泵效持续下降', scope: 'W-5', content: 'W-5 泵效 6 小时由 0.62 降至 0.47，低于基准 0.55',
    status: 'active', hit_count: 2, suppressed_count: 1,
    first_seen: min(200), last_seen: min(150),
    acknowledged_by: null, acknowledged_at: null, resolved_by: null, resolved_at: null, resolution: null,
    escalations: [], trace_id: 'tr-51ab3e77',
  },
  {
    alert_id: 'alt-92ce08d4', dedup_key: 'W-2|井口温度|偏高', level: '提醒', source: 'environment_safety',
    cause: '井口温度偏高', scope: 'W-2', content: 'W-2 井口温度 46.3℃，高于同期均值 38℃',
    status: 'acknowledged', hit_count: 1, suppressed_count: 0,
    first_seen: min(400), last_seen: min(400),
    acknowledged_by: '张伟', acknowledged_at: min(370), resolved_by: null, resolved_at: null, resolution: null,
    escalations: [], trace_id: 'tr-1c9d62be',
  },
  {
    alert_id: 'alt-5f1aa783', dedup_key: 'W-6|日产气量|下降', level: '预警', source: 'production_analysis',
    cause: '日产气量下降', scope: 'W-6', content: 'W-6 日产气量 24h 下降 18%，疑似节流阀冰堵',
    status: 'resolved', hit_count: 4, suppressed_count: 2,
    first_seen: min(1500), last_seen: min(1300),
    acknowledged_by: '李强', acknowledged_at: min(1290), resolved_by: '李强', resolved_at: min(1200),
    resolution: '节流阀伴热带投运，产量恢复',
    escalations: [{ ts: min(1400), kind: 'timeout', from_level: '提醒', to_level: '预警', notified: ['班长'], note: '超时未确认自动升级' }],
    trace_id: 'tr-3e77ac19',
  },
  {
    alert_id: 'alt-6d3b5f01', dedup_key: 'W-1|电流|波动', level: '提示', source: 'data_collector',
    cause: '电流波动', scope: 'W-1', content: 'W-1 上行电流波动幅度 ±15%，观察中',
    status: 'active', hit_count: 1, suppressed_count: 0,
    first_seen: min(30), last_seen: min(30),
    acknowledged_by: null, acknowledged_at: null, resolved_by: null, resolved_at: null, resolution: null,
    escalations: [], trace_id: '',
  },
]

/** 工单（状态机各阶段覆盖） */
export const WORK_ORDERS: WorkOrder[] = [
  {
    order_id: 'ord-1024', alert_id: 'alt-a31f09c2', title: 'W-3 井口压力超限处置',
    priority: '紧急', device_id: 'DEV-003', well_id: 'W-3', status: 'processing',
    assignee: '张伟', actions_taken: '已现场核查井口针阀开度', resolution: null, actual_cause: null,
    created_at: min(90), updated_at: min(40), resolved_at: null, closed_at: null, escalations: [],
  },
  {
    order_id: 'ord-1025', alert_id: 'alt-77bd41e5', title: 'W-5 泵效下降分析',
    priority: '预警', device_id: 'DEV-005', well_id: 'W-5', status: 'pending',
    assignee: null, actions_taken: null, resolution: null, actual_cause: null,
    created_at: min(150), updated_at: min(150), resolved_at: null, closed_at: null, escalations: [],
  },
  {
    order_id: 'ord-1023', alert_id: 'alt-5f1aa783', title: 'W-6 日产气量下降处置',
    priority: '预警', device_id: 'DEV-006', well_id: 'W-6', status: 'resolved',
    assignee: '李强', actions_taken: '投运伴热带', resolution: '产量恢复至 3.1×10⁴m³/d', actual_cause: null,
    created_at: min(1400), updated_at: min(1200), resolved_at: min(1200), closed_at: null,
    escalations: [],
  },
  {
    order_id: 'ord-1021', alert_id: 'alt-9c0174e2', title: 'W-2 套压例行核查',
    priority: '预警', device_id: 'DEV-002', well_id: 'W-2', status: 'closed',
    assignee: '王芳', actions_taken: '现场校验压力表', resolution: '更换压力表', actual_cause: '压力表冻堵失效，非真实超压',
    created_at: min(2900), updated_at: min(2600), resolved_at: min(2700), closed_at: min(2600),
    escalations: [],
  },
]

/** 知识候选队列 */
export const KB_CANDIDATES: KBCandidate[] = [
  {
    candidate_id: 'cand-1a2b3c01', source_type: 'workorder', source_id: 'ord-1021',
    title: '案例：采气井套压误报——压力表冻堵排查',
    doc_type: '案例', source_ref: '工单 ord-1021',
    text: '现象：W-2 套压告警，现场实测正常。\n原因：压力表冻堵失效导致误报。\n处置：更换压力表并加装保温。\n经验：冬季采气井压力类告警需先排除仪表冻堵。',
    tags: ['采气井', '套压', '仪表冻堵'], status: 'pending', doc_id: null,
    review_note: null, reviewed_by: null, reviewed_at: null, created_at: min(2500),
  },
  {
    candidate_id: 'cand-1a2b3c02', source_type: 'alert_dedup', source_id: 'W-3|井口压力|超限',
    title: '高频告警沉淀：W-3 井口压力反复超限',
    doc_type: '案例', source_ref: '去重键 W-3|井口压力|超限',
    text: 'W-3 井口压力 24h 内 3 次超限（阈值 1.50 MPa），均伴随回压升高。建议检查外输管线是否结垢。',
    tags: ['井口压力', '高频告警'], status: 'pending', doc_id: null,
    review_note: null, reviewed_by: null, reviewed_at: null, created_at: min(80),
  },
  {
    candidate_id: 'cand-1a2b3c03', source_type: 'trace', source_id: 'tr-3e77ac19',
    title: '问答沉淀：日产气量下降疑似冰堵如何处置？',
    doc_type: '案例', source_ref: '链路 tr-3e77ac19',
    text: '问题：W-6 日产气量下降 18% 如何处置？\n结论：疑似节流阀冰堵。\n依据：日产气量=-18%；井口温度=12.4℃；处置：投运伴热带后恢复。',
    tags: ['气井', '冰堵'], status: 'pending', doc_id: null,
    review_note: null, reviewed_by: null, reviewed_at: null, created_at: min(1190),
  },
  {
    candidate_id: 'cand-1a2b3c04', source_type: 'workorder', source_id: 'ord-1019',
    title: '案例：抽油机平衡块松动导致电流波动',
    doc_type: '案例', source_ref: '工单 ord-1019',
    text: '现象：W-1 上行电流波动 ±15%。\n原因：曲柄平衡块固定螺栓松动。\n处置：紧固螺栓并复测平衡率至 92%。',
    tags: ['抽油机', '电流波动'], status: 'approved', doc_id: 'kb-9d01',
    review_note: '内容完整，入库', reviewed_by: '班长', reviewed_at: min(5000), created_at: min(6000),
  },
]

/** 知识库文档 */
export const KB_DOCS: KBDocumentView[] = [
  { doc_id: 'kb-9d01', title: '抽油机平衡块松动导致电流波动案例', doc_type: '案例', source_ref: '工单 ord-1019', summary: '现象：W-1 上行电流波动 ±15%。原因：曲柄平衡块固定螺栓松动。处置：紧固螺栓并复测平衡率至 92%。', tags: ['抽油机', '电流波动'], status: 'ready', chunk_count: 3, error: null, created_at: min(5000), updated_at: min(4980) },
  { doc_id: 'kb-9d02', title: '采气井冬季防冻堵操作规程', doc_type: '规程', source_ref: 'QS-WX-2024-011', summary: '冬季井口压力表、节流阀易冻堵，巡检需核查伴热带运行状态；压力类告警先排除仪表冻堵再判断真实超压。', tags: ['采气井', '防冻'], status: 'ready', chunk_count: 5, error: null, created_at: min(8000), updated_at: min(7900) },
  { doc_id: 'kb-9d03', title: '井口压力超限应急处置预案', doc_type: '预案', source_ref: 'YA-WX-2024-003', summary: '井口压力超阈值 15% 以上时：1. 核查外输管线回压；2. 检查针阀开度；3. 必要时降冲次；4. 30 分钟内上报。', tags: ['井口压力', '应急'], status: 'ready', chunk_count: 4, error: null, created_at: min(9000), updated_at: min(8800) },
  { doc_id: 'kb-9d04', title: '泵效下降常见原因清单', doc_type: '其他', source_ref: '技术总结 2024-Q3', summary: '泵效下降常见原因：气体影响、供液不足、泵漏失、结蜡。对应手段：调冲次、调沉没度、热洗。', tags: ['泵效', '采油'], status: 'indexing', chunk_count: 0, error: null, created_at: min(20), updated_at: min(19) },
  { doc_id: 'kb-9d05', title: '钻井泥浆密度窗口参考', doc_type: '规程', source_ref: 'QS-ZJ-2023-021', summary: '南区钻井平台泥浆密度窗口 1.15–1.25 g/cm³，漏失层位需降至下限并随钻监测。', tags: ['钻井', '泥浆'], status: 'failed', chunk_count: 0, error: '分块超时：文档过大', created_at: min(3000), updated_at: min(2900) },
  { doc_id: 'kb-9d06', title: '抽油机电流异常诊断手册', doc_type: '其他', source_ref: '技术手册 CY-2024-05', summary: '上行电流持续抬升先查平衡率与负载，再查皮带/减速箱；电流波动 >±10% 需停机检查。', tags: ['抽油机', '电流'], status: 'ready', chunk_count: 6, error: null, created_at: min(6000), updated_at: min(5800) },
  { doc_id: 'kb-9d07', title: '钻井钻压遇阻处置流程', doc_type: '规程', source_ref: 'QS-ZJ-2024-008', summary: '钻压异常爬升超过阈值时：减钻压、提转速、循环洗井；若伴扭矩升高立即停钻分析岩屑。', tags: ['钻井', '钻压'], status: 'ready', chunk_count: 4, error: null, created_at: min(4500), updated_at: min(4400) },
  { doc_id: 'kb-9d08', title: '井口泄漏高风险联锁处置预案', doc_type: '预案', source_ref: 'YA-WX-2024-009', summary: '井口压力骤降判为泄漏高风险：自动停井、切断上游、布设警戒；处置完成验收后方可复产。', tags: ['井口压力', '泄漏', '联锁'], status: 'ready', chunk_count: 5, error: null, created_at: min(3500), updated_at: min(3400) },
  { doc_id: 'kb-9d09', title: '沉没度优化调整指南', doc_type: '其他', source_ref: '技术总结 2024-Q2', summary: '沉没度低于 250m 易供液不足，高于 400m 增加举升能耗；按动液面动态调至 300–350m。', tags: ['泵效', '沉没度'], status: 'ready', chunk_count: 3, error: null, created_at: min(7000), updated_at: min(6900) },
  { doc_id: 'kb-9d10', title: '节流阀冰堵快速解堵操作卡', doc_type: '规程', source_ref: 'QS-WX-2024-015', summary: '确认冰堵后投用伴热带并小开度活动阀杆，严禁强行大扭矩开关；解堵后核验压力恢复曲线。', tags: ['采气井', '冰堵', '节流阀'], status: 'ready', chunk_count: 3, error: null, created_at: min(5500), updated_at: min(5400) },
  { doc_id: 'kb-9d11', title: '外输管线结垢清洗方案', doc_type: '预案', source_ref: 'FA-YX-2024-002', summary: '外输回压升高判为结垢：采用化学清洗 + 机械清管，清洗期间相关井限产 20%。', tags: ['外输管线', '结垢'], status: 'ready', chunk_count: 4, error: null, created_at: min(4000), updated_at: min(3900) },
  { doc_id: 'kb-9d12', title: '气体影响泵效的判别与对策', doc_type: '案例', source_ref: '工单 ord-1015', summary: 'W-5 泵效骤降伴电流波动，判为气体影响；下气锚并调小冲次后泵效回升 18%。', tags: ['泵效', '气锚'], status: 'ready', chunk_count: 3, error: null, created_at: min(2500), updated_at: min(2400) },
]

/** 图谱（按社区聚合，与 graph_repo 结构一致） */
export const GRAPH_NODES: GraphNode[] = [
  { name: 'W-3', entity_type: '井', description: '3号采油井，中区 C 排', sources: ['kb-9d03'], degree: 6 },
  { name: 'W-6', entity_type: '井', description: '6号采气井，西区 E 排', sources: [], degree: 4 },
  { name: 'W-2', entity_type: '井', description: '2号采气井，东区 B 排', sources: ['kb-9d02'], degree: 3 },
  { name: 'W-1', entity_type: '井', description: '1号采油井，东区 A 排', sources: ['kb-9d01'], degree: 3 },
  { name: 'W-5', entity_type: '井', description: '5号采油井，西区 D 排', sources: [], degree: 2 },
  { name: '井口压力超限', entity_type: '风险', description: '井口压力超过安全阈值', sources: ['kb-9d03'], degree: 4 },
  { name: '冰堵', entity_type: '风险', description: '节流阀/管线冰堵导致产量下降', sources: [], degree: 3 },
  { name: '仪表冻堵', entity_type: '风险', description: '压力表冻堵导致测量失真', sources: ['kb-9d02'], degree: 2 },
  { name: '外输管线', entity_type: '概念', description: '井口至联合站外输管线', sources: ['kb-9d03'], degree: 3 },
  { name: '节流阀', entity_type: '概念', description: '气井节流调产装置', sources: [], degree: 3 },
  { name: '伴热带', entity_type: '概念', description: '电伴热防冻装置', sources: [], degree: 2 },
  { name: '泵效', entity_type: '概念', description: '抽油泵排量效率', sources: [], degree: 2 },
  { name: '井口压力超限应急处置预案', entity_type: '文档', description: 'YA-WX-2024-003', sources: ['kb-9d03'], degree: 2 },
  { name: '采气井冬季防冻堵操作规程', entity_type: '文档', description: 'QS-WX-2024-011', sources: ['kb-9d02'], degree: 2 },
]

export interface MockGraphEdge { source: string; target: string; relation: string; weight: number }
export const GRAPH_EDGES: MockGraphEdge[] = [
  { source: 'W-3', target: '井口压力超限', relation: '发生', weight: 3 },
  { source: 'W-3', target: '外输管线', relation: '连接', weight: 2 },
  { source: '井口压力超限', target: '外输管线', relation: '诱因', weight: 2 },
  { source: '井口压力超限', target: '井口压力超限应急处置预案', relation: '关联文档', weight: 2 },
  { source: 'W-6', target: '冰堵', relation: '发生', weight: 2 },
  { source: '冰堵', target: '节流阀', relation: '部位', weight: 2 },
  { source: '冰堵', target: '伴热带', relation: '处置', weight: 2 },
  { source: 'W-2', target: '仪表冻堵', relation: '发生', weight: 1 },
  { source: '仪表冻堵', target: '采气井冬季防冻堵操作规程', relation: '关联文档', weight: 1 },
  { source: 'W-2', target: '采气井冬季防冻堵操作规程', relation: '适用', weight: 1 },
  { source: 'W-1', target: '泵效', relation: '指标', weight: 1 },
  { source: 'W-5', target: '泵效', relation: '指标', weight: 2 },
  { source: 'W-6', target: '节流阀', relation: '装备', weight: 1 },
]

export const GRAPH_COMMUNITIES: GraphCommunity[] = [
  { community_id: 'com-w3', title: 'W-3 井口压力风险簇', summary: 'W-3 井口压力反复超限，关联外输管线结垢与应急预案', members: ['W-3', '井口压力超限', '外输管线', '井口压力超限应急处置预案'], size: 4 },
  { community_id: 'com-w6', title: 'W-6 冰堵处置簇', summary: 'W-6 节流阀冰堵导致产气下降，伴热带为有效处置手段', members: ['W-6', '冰堵', '节流阀', '伴热带'], size: 4 },
  { community_id: 'com-w2', title: 'W-2 仪表冻堵簇', summary: 'W-2 压力表冻堵误报，关联冬季防冻规程', members: ['W-2', '仪表冻堵', '采气井冬季防冻堵操作规程'], size: 3 },
  { community_id: 'com-oil', title: '采油井泵效簇', summary: 'W-1/W-5 泵效指标相关问题', members: ['W-1', 'W-5', '泵效'], size: 3 },
]

/** 事件日历（检修 / 停电 / 限产） */
export const CALENDAR_EVENTS: CalendarEventView[] = [
  { event_type: '检修', wells: ['W-3'], start: '12:00', end: '14:00', desc: 'W-3 井口针阀拆检，期间数据中断' },
  { event_type: '停电', wells: ['W-1', 'W-5'], start: '09:00', end: '09:40', desc: '西区线路计划停电' },
  { event_type: '限产', wells: ['W-6'], start: '00:00', end: '23:59', desc: '外输受限，W-6 限产 20%' },
]

/** 快捷提问卡片 */
export const QUICK_PROMPTS = [
  { title: '今天有哪些异常井？', desc: '汇总当前活动告警与异常指标', q: '今天有哪些异常井？' },
  { title: 'W-3 最近 24h 井口压力趋势', desc: '查看趋势与阈值偏离', q: 'W-3 最近24小时井口压力趋势怎么样？' },
  { title: 'W-6 产气量下降原因', desc: '诊断分析 + 处置建议', q: 'W-6 日产气量为什么下降？' },
  { title: '井口压力超限怎么办？', desc: '检索应急处置预案', q: '井口压力超限应该怎么处置？' },
]

/** 常见关闭原因快选 */
export const CLOSE_CAUSE_PRESETS = ['设备误报', '仪表故障', '工况波动，已恢复', '外输管线结垢', '冰堵已解除', '计划检修导致']

export const LEVEL_ORDER: Level[] = ['提示', '提醒', '预警', '紧急']
