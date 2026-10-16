# 智慧井场值班台 · 前端开发提示词

> **版本**：V1.0
> **适用场景**：后端已完成（10 节点多智能体 · mock 数据源），本提示词用于生成前端代码
> **技术栈**：Vue 3.4+ · Vite 5 · TypeScript · Element Plus · Pinia · Vue Router 4 · ECharts · axios
> **代码落位**：`smart-wellsite/apps/admin/`（值班台 + 管理后台）
> **运行环境**：Windows · conda 环境 `E:\Anaconda\envs\zhihui` · 命令一律加 `PYTHONNOUSERSITE=1`

---

## 一、使用说明

**接入方式**：`系统级共享前缀（前端，第二节）` + `该页面的页面提示词（第三节）` 拼接，作为该页面/模块的开发提示词。

**三条铁律（先读，再写代码）**：

1. **只对接真实后端接口，不伪造业务数据。** 凡后端未提供的接口，必须在 `src/api/stub/` 下按第四节 4.2 的约定契约写桩，并在 UI 上显式标注「演示数据」，禁止把桩数据当成真实结果静默展示。
2. **前端没有任何控制权。** 所有涉及设备/处置的动作（改参数、工单闭环、图谱重建）一律渲染为「建议 + 需人工确认」，点击后必须走二次确认弹窗，禁止出现「一键执行」文案。
3. **先结论、后依据、再建议。** 每个结论必须携带置信度与引用来源；数据缺口必须显式展示；多 Agent 冲突必须并列，禁止强行合并成一句话。

**需要替换的占位符**：`{API_BASE}`（默认 `http://127.0.0.1:8000`）、`{WS_URL}`（默认 `ws://127.0.0.1:8000/ws`）。

**联调前置（后端启动命令）**：

```powershell
cd e:\BaiduNetdiskDownload\zengke\code\zhihui\smart-wellsite
$env:PYTHONNOUSERSITE=1
E:\Anaconda\envs\zhihui\python.exe -m uvicorn apps.gateway.main:app --port 8000
```

- 后端无鉴权：**初版不做登录页**（或保留登录页但标注「后端未就绪」），`withCredentials` 必须为 `false`。
- 当前 CORS 为 `allow_origins=["*"]` + `allow_credentials=True`，浏览器在携带凭证时会拒绝通配源；后续接入登录时需后端改为显式 origin，前端同步开启凭证。
- 可访问 `{API_BASE}/docs` 与 `/openapi.json` 自动生成 TS 类型，优先用它而不是手写接口类型。

---

## 二、系统级共享前缀（所有页面共用，逐页拼接）

```text
你为「智慧井场」多智能体系统开发前端。后端已完成 10 个节点（6 个 LLM Agent + 4 个确定性节点），
数据源为 mock，前端只需可视化与交互，不得伪造业务数据。

【安全红线（UI 化，最高优先级）】
1. 无执行权：任何设备操作/处置动作只能渲染为「建议」，并强制显示「需人工确认后执行」；
   点击后必须弹二次确认（展示动作、影响对象、trace_id），确认后仅提交「确认记录」，不得触发设备指令。
2. 数据合规：井号、坐标、人员信息展示需脱敏开关；不得显示任何未经后端返回的数据。
3. 一切留痕：每个结论卡片必须显示 citations（来源）与 confidence_level；引用为空时必须显示「无来源」警示样式，
   禁止隐藏或美化。

【数据展示规范】
- 数值必须带单位与口径（如「井口日产量 18.1 t/d」而非「产量 18.1」）。
- 置信度三态：高=绿、中=蓝、低=橙；低置信度结论必须附加「需补充信息」提示。
- 数据缺口（quality.gap / 缺数时段）必须用醒目的「缺数」徽标展示，禁止静默填 0 或画连续曲线。
- partial=true（超时熔断/降级）时，页面顶部显示降级横幅，说明「部分节点未完成，结果不完整」。

【多 Agent 协作规范】
- results 中每个节点的结论独立成卡，保留 agent 名称、置信度、耗时、needs_review 标记。
- conflicts 非空时，冲突各方并列展示（左右对照或并列卡片），禁止合成单一结论。
- need_clarify=true 时，不派发查询，而是把 clarify_options 渲染成可点选的快捷选项，点击后回填并重新提问。

【回答与文案规范】
- 简体中文，简洁直接；先结论再依据再建议。
- 时间范围、井号、指标口径必须完整展示在结论头部，便于值班员核对。
- 错误/超时使用中性文案（如「节点超时，已熔断」），禁止用「系统故障」等引起恐慌的措辞。
```

---

## 三、页面提示词

### 3.1 值班对话页（`/chat`，主入口）

```text
【页面目标】值班人员与系统的唯一自然语言入口，把多 Agent 聚合结果组织成可核对的结论卡。

【布局】左侧会话列表（按 session_id）；中间对话流；右侧「本轮协作链路」侧栏。

【核心交互】
1. 输入问题 → POST {API_BASE}/api/v1/chat，body {message, session_id}；session_id 首次由前端生成并持久化（localStorage）。
2. need_clarify=true：不显示结论，渲染 clarify_options 为可点按钮（如「井口产量（口径：井口产量）」「净化产量（口径：净化产量）」），
   点击后以该选项作为新一轮消息继续提问。必须提示「系统不会猜测，请确认以下信息」。
3. 结论卡：展示 reply（已含结论/依据/建议分段）→ 用换行分段渲染为「结论 / 依据 / 建议 / 分歧 / 报告」区块。
4. 依据区：展示 citations，每条前缀标注来源类型（TDengine / 知识库 / 视频 / 环境监测）；空则显示「无来源」警示。
5. 置信度标签：confidence_level（高/中/低）以三色 Tag 展示；partial=true 时卡片加降级边框。
6. 右侧链路侧栏：列出 tools_called（10 个节点的中文名映射），每项显示 conclusion / confidence / elapsed_ms /
   needs_review / error；error 或 partial 用中性提示样式。
7. trace_id 可点击复制，并跳转链路追踪页（3.3）。
8. 可选：WebSocket 走 {WS_URL}，接收 {type:"stream", content} → {type:"done", reply,...}，实现逐字渲染；
   连接失败自动回退到 HTTP POST，并提示「已切换为整段返回」。

【禁止】不得在前端拼接或改写后端 reply 的业务含义；不得隐藏 conflicts 与 citations。
```

### 3.2 告警与工单审核页（`/alerts`）

```text
【页面目标】告警分级展示、去重聚合核对、工单人工闭环（Human-in-the-loop）。

【数据来源】GET {API_BASE}/api/v1/alerts（契约见 4.2）。后端未就绪时用 stub，页面顶部必须标「演示数据」。

【布局】顶部筛选（等级 / 时间范围 / 井号 / 状态）；中部告警表格；右侧工单详情抽屉。

【核心交互】
1. 分级映射可视化：提醒=灰、预警=橙、紧急=红；紧急行固定置顶并加声光提示开关（前端本地音效，默认关闭需手动开启）。
2. 去重聚合：同一 dedup_group 的多条告警折叠为一行，显示「聚合 N 条 / 最近一次时间 / 是否已升级」，
   展开可看明细；不得把聚合后的多条渲染成多行重复告警（防告警疲劳）。
3. 工单闭环：详情抽屉展示事件、agent 建议、来源 trace_id；确认按钮文案为「确认处置（人工）」，
   点击弹二次确认，提交 POST {API_BASE}/api/v1/orders/{id}/confirm，成功后状态置「已确认」。
4. 超时升级：status=待确认且超时（阈值由后端返回 timeout_at）时，行标记「已超时，建议升级」。
5. 旁路保障说明：页面固定位置显示一行说明「本系统为增强链路，原有报警链路不受影响」。
6. 每条告警必须展示 level、content、targets（通知对象）、trace_id、dedup 计数。

【禁止】不得提供「批量一键处置」这类绕过人工确认的入口。
```

### 3.3 多 Agent 链路追踪页（`/traces`）

```text
【页面目标】trace_id 全链路可回溯：看清一次请求经过哪些节点、各自耗时、置信度与是否熔断。

【数据来源】GET {API_BASE}/api/v1/traces/{trace_id}、GET {API_BASE}/api/v1/traces?session_id=（契约见 4.2）。

【布局】上方 trace 检索（按 trace_id / session_id / 时间范围）；中部横向时序甘特（每节点一条泳道）；
下方节点详情表。

【核心交互】
1. 甘特图：ECharts custom series，X 轴为时间，每条泳道为一个节点（中文名 = 10 节点映射），
   条形长度 = elapsed_ms，颜色 = 置信度高/中/低，超时熔断的条用斜纹标注 partial。
2. 节点详情表：agent / conclusion / confidence / evidence（若有）/ suggestion / needs_review / partial / error / elapsed_ms。
3. 点击节点 → 展示该节点的原始 payload 与返回 JSON（只读折叠面板）。
4. 顶部统计：总耗时、节点数、熔断数、冲突数。调用预算提示：单次请求 ≤5 次调用，超过时展示「已触及预算，结果不完整」。
5. 若无 evidence 字段（后端当前 results 视图不返回），该列显示「后端未返回」，不得前端编造。

【禁止】不得用「绿色通过」等结论性颜色暗示业务正确；颜色只表达置信度与耗时。
```

### 3.4 知识与报表页（`/knowledge`）

```text
【页面目标】规程与案例问答（RAG）+ 班报/日报/月报生成与导出。

【核心交互】
1. 知识问答：输入问题 → POST /api/v1/chat（意图为 knowledge，走报表知识 Agent）；
   回答区必须展示 source_refs，每条可点击查看条目详情（4.2 的 /api/v1/kb/documents/{id}）。
2. 检索不到时，页面按后端返回原文展示「知识库中暂无此内容，建议联系工艺负责人补充」，
   并提供「去管理后台上传」按钮（跳 3.6）。禁止用前端拼接通用常识兜底。
3. 安全类回答必须固定展示提示条「以现场应急预案为准」。
4. 报表：选择井号 + 时间范围 + 报表类型（班报/日报/月报）→ 生成结果分区展示；
   数值带单位与口径；缺数时段以「缺数」徽标标出；支持导出 Markdown / CSV。
5. 报表与问答分别保留历史记录，可回看。

【禁止】不得在检索为空时编造规程内容；不得省略 source_refs。
```

### 3.5 井场总览页（`/overview`）

```text
【页面目标】一屏看清 7 口井的井型、状态与关键指标，叠加事件日历与环境/视频事件。

【数据来源】GET /api/v1/wells、/api/v1/wells/{id}、/api/v1/telemetry、/api/v1/events/calendar（契约见 4.2）。

【布局】左侧井列表（W-1~W-7，按井型分组：采油/采气/钻井）；中间关键指标卡片 + 趋势折线；右侧事件时间轴。

【核心交互】
1. 井卡片：井号（W-3）、井型中文（采油/采气/钻井）、设备号、状态；点击切换选中井。
2. 关键指标按井型渲染（采油：井口日产量/泵效/沉没度/电流/套压/冲次；采气：日产气量/井口压力/节流前压力/井口温度；
   钻井：钻压/转速/泥浆密度），卡片显示当前值与趋势箭头（上行/下行/平稳）。
3. 趋势折线：ECharts，缺口时段必须断线（null 点）而非连线，并在图上标注缺口区间。
4. 事件时间轴：展示事件日历（检修/停电/限产），与趋势图时间轴对齐；点击事件高亮对应时段，
   提示「该时段产量变化可能由人工事件引起，非设备故障」。
5. 环境与视频事件角标：H2S 等超阈值、视频识别事件以角标展示等级，点击跳告警页。
6. 数据缺失/传感器离线必须显式展示为「数据缺失」，不得静默。

【禁止】不得跨井型套用指标（如给采气井展示泵效）；不得在缺口时段画连续曲线。
```

### 3.6 管理后台 · RAG 知识库（`/admin/kb`）

```text
【页面目标】支撑 RAG 的知识增长：文档上传 → 结构感知分块 → 向量化 → 入库 → 检索测试。

【数据来源】契约见 4.2（kb 系列接口）。后端未就绪时全部走 stub 并标「演示数据」。

【核心交互】
1. 文档列表：标题 / 类型（规程·预案·案例）/ 分块数 / 向量化状态（待处理·进行中·完成·失败）/ 更新时间 / 操作。
2. 上传：支持 .md / .txt / .pdf，上传后 POST 触发索引；索引进度用轮询 + 进度条展示，
   分块结果可预览（展示 chunk 文本 + 来源章节），让用户核对分块质量。
3. 检索测试：输入 query + top_k → 展示命中条目、相似度分数、命中的 chunk 片段；
   用于人工评估召回质量，并可一键「把该问题发给值班助手」联动 3.1。
4. 规模增长看板：文档数 / 分块数 / 近 7 天入库趋势（ECharts）。
5. 删除需二次确认，提示「删除将同时移除向量索引，可能影响问答召回」。

【禁止】不得提供「无需人工确认的全量重建」按钮；不得把索引进度做成假进度条。
```

### 3.7 管理后台 · 知识图谱（`/admin/graph`）

```text
【页面目标】支撑知识图谱增长：实体/关系/社区的可视化、增量构建与重建。

【数据来源】契约见 4.2（graph 系列接口）。后端未就绪时走 stub 并标「演示数据」。

【核心交互】
1. 图谱可视化：ECharts graph 力导向布局，节点颜色 = 实体类型（10 类，如设备/井/故障/规程/指标等），
   节点大小 = 度数，边 = 关系（11 类）；支持按类型过滤、按关键词搜索高亮、点击节点查看属性与邻居。
2. 社区视图：展示 Louvain 社区及其摘要（社区编号、成员数、摘要文本）；点社区高亮其成员节点。
3. 统计卡片：实体数 / 关系数 / 社区数 / 平均度；配一条「规模增长曲线」（按构建批次）。
4. 增量构建：展示待处理 chunk 数，按钮文案「开始增量构建（需人工确认）」，二次确认后 POST 触发；
   构建过程展示进度与日志（只读），禁止在前端推断抽取结果。
5. 三元组抽样核对：随机抽样展示 subject - 关系 - object - 置信度，供人工抽查抽取质量。

【禁止】不得在前端做实体消歧或合并；不得把低置信度三元组过滤掉不展示（应标注为「待复核」）。
```

---

## 四、接口契约

### 4.1 已实现（可直接对接，当前可跑通）

| 接口 | 说明 |
| --- | --- |
| `GET /healthz` | 返回 `{status, timestamp, version, services{gateway, llm, orchestrator, agents}}`；首页可用它做服务状态灯 |
| `POST /api/v1/chat` | 值班助手入口，见下方 ChatResponse |
| `WS /ws` | 发送 `{message, session_id}`；接收 `{type:"stream", content}` 与 `{type:"done", reply, trace_id, citations, conflicts, partial}` |
| `GET /metrics` | Prometheus 文本指标（可对接监控页） |
| `GET /docs`、`/openapi.json` | OpenAPI 文档（用于生成 TS 类型） |

**ChatRequest**：`{ message: string(必填), session_id?: string, context?: object }`

**ChatResponse**：

```ts
{
  reply: string;                    // 已分段的回答（含结论/依据/建议/分歧/报告）
  session_id: string;
  trace_id: string;                 // 形如 tr-xxxxxxxx
  citations: string[];              // 引用来源，需逐条展示
  confidence_level: "高"|"中"|"低"|null;
  need_clarify: boolean;
  clarify_options: string[];        // 澄清候选，渲染为可点选项
  conflicts: string[];              // 多 Agent 分歧，必须并列展示
  partial: boolean;                 // 降级/熔断标记
  tools_called: string[];           // 参与本轮编排的节点名
  results: Array<{
    agent: string;                  // 节点名
    conclusion: string;
    confidence: number;             // 0~1
    needs_review: boolean;          // 需人工复核
    partial: boolean;
    error: string | null;
    elapsed_ms: number | null;
  }>;
  timestamp: string;
}
```

**10 个节点名 → 中文名映射（固定，不得改写）**：

| 节点名 | 中文名 | 节点名 | 中文名 |
| --- | --- | --- | --- |
| `duty_assistant` | 值班助手 | `device_diagnosis` | 设备诊断 |
| `orchestrator` | 井场调度 | `production_analysis` | 生产分析 |
| `data_collector` | 数据采集 | `safety_risk` | 安全风险 |
| `video_intelligence` | 视频智能 | `alert_handler` | 告警处置 |
| `environment_safety` | 环境安全 | `report_knowledge` | 报表知识 |

### 4.2 待后端补齐（前端按此契约写 adapter，后端补齐后零改动切换）

> **重要**：以下接口**后端尚未实现**。前端必须在 `src/api/stub/` 提供桩数据，UI 上显式标注「演示数据」，
> 并在 `src/api/` 保持与真实实现相同的函数签名；后端就绪后仅切换实现，页面代码不动。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/wells` | 井号表（含井型、设备号、状态） |
| GET | `/api/v1/wells/{well_id}` | 单井详情 |
| GET | `/api/v1/telemetry?tag=&start=&end=` | 时序查询（返回 series + quality.gap + events） |
| GET | `/api/v1/events/calendar?from=&to=` | 事件日历（检修/停电/限产） |
| GET | `/api/v1/alerts?level=&status=&from=&to=` | 告警列表（含 `dedup_group`、`count`、`escalated`、`timeout_at`） |
| GET | `/api/v1/orders?status=` | 工单列表 |
| POST | `/api/v1/orders/{id}/confirm` | 工单人工确认闭环 |
| GET | `/api/v1/traces?session_id=&from=&to=` | 会话链路列表 |
| GET | `/api/v1/traces/{trace_id}` | 链路详情（建议后端补充 `evidence`、`suggestion`、`parameter_advice`、`data`） |
| GET | `/api/v1/kb/documents` | 知识库文档列表（状态/分块数） |
| POST | `/api/v1/kb/documents` | 上传文档（multipart） |
| POST | `/api/v1/kb/documents/{id}/index` | 触发分块与向量化 |
| GET | `/api/v1/kb/search?q=&top_k=` | 检索测试（返回命中条目与分数） |
| DELETE | `/api/v1/kb/documents/{id}` | 删除文档与向量索引 |
| GET | `/api/v1/graph/stats` | 实体/关系/社区规模统计 |
| GET | `/api/v1/graph/entities?type=&q=` | 实体检索 |
| GET | `/api/v1/graph/neighbors/{entity_id}` | 邻居查询 |
| GET | `/api/v1/graph/communities` | 社区及摘要 |
| POST | `/api/v1/graph/rebuild` | 增量构建/重建（需人工确认） |

**建议后端补充 `evidence` 的理由**：当前 `ChatResponse.results` 只返回 conclusion/confidence，
链路页与结论卡的「依据」只能靠 reply 文本解析。补齐 `evidence: {ts, metric, value, trend, source}[]` 后，
依据区可结构化渲染、可排序、可跳转时序图。

### 4.3 当前可复现的演示场景（用于联调验收）

| 提问 | 预期表现 |
| --- | --- |
| 「3号井今天的井口日产量是多少？」 | 走 data_collector + production_analysis，带 TDengine 引用 |
| 「3号井今天的产量是多少？」 | `need_clarify=true`，「产量」多口径 → 渲染为候选按钮，不猜测 |
| 「3号井上周的井口日产量是多少？」 | `need_clarify=true`，「上周」有歧义 → 追问时间段 |
| 「3号井今天设备有什么故障？」 | 诊断「供液不足」+ 自动追加生产分析复核，`needs_review=true` |
| 「W-1今天设备有什么故障？」 | 命中事件日历「检修」→ 归因人工事件，不误判为设备故障 |
| 「W-7井口有没有硫化氢风险？」 | safety_risk + environment_safety + video_intelligence + alert_handler，H2S 预警、派生工单 |
| 「抽油机供液不足怎么处理？」 | 报表知识 Agent 命中《抽油机操作规程》并返回 source_refs |
| 「W-9今天的井口日产量是多少？」 | 井号不存在 → `need_clarify=true`，给出 W-1~W-7 候选 |
| 「你好」 | `general`，不派发节点，返回助手能力介绍 |

---

## 五、组件与设计规范

**通用组件清单（命名固定，便于跨页复用）**：

| 组件 | 职责 | 关键约束 |
| --- | --- | --- |
| `ConclusionCard` | 结论文本分段 + 置信度 + 缺数/降级徽标 | 必须显示置信度与来源数量 |
| `ConfidenceTag` | 高/中/低三色标签 | 低置信度附「需补充信息」 |
| `EvidenceList` | citations / evidence 列表 | 空列表显示「无来源」警示样式 |
| `ClarifyPrompt` | clarify_options → 可点选项 | 必须提示「系统不猜测」 |
| `ConflictPanel` | conflicts 并列展示 | 禁止合并为单一结论 |
| `GapBadge` | 数据缺口徽标 | 与折线断点联动 |
| `DegradedBanner` | partial/降级横幅 | 说明「部分节点未完成」 |
| `ConfirmActionButton` | 一切处置动作的唯一入口 | 强制二次确认 + 展示 trace_id |
| `AgentTracePanel` | 协作链路侧栏 | 显示 10 节点耗时/置信度/partial |
| `AlertLevelTag` | 提醒/预警/紧急 | 颜色语义固定，紧急置顶 |
| `GraphView` | 知识图谱力导向图 | 不做前端消歧 |
| `TrendChart` | 时序折线 | 缺口断线，不插值 |

**状态机**（每页统一）：`idle → loading → ok / clarify / partial / degraded / error`
- `partial`：部分节点熔断，展示已完成部分 + 降级横幅。
- `error`：请求失败或编排器未就绪，展示兜底文案「当前智能问答服务不可用，异常检测与告警链路不受影响」。

**信息层级**：结论 > 依据 > 建议 > 原始数据。危险色（红）仅用于「紧急」等级，不得用于普通错误提示。

**响应式**：以 1440×900 值班大屏为主，兼容 1920×1080；关键结论区在窄屏优先展示。

---

## 六、交付与验收

**可靠性五件套**（提示词里每条「必须/禁止」都对应一个真实故障点，逐条自检）：

1. 实体先校验再查询 → `need_clarify` 必须渲染为可选按钮，不得静默用默认值继续查询。
2. 结论必带置信度与引用 → 结论卡无置信度或无来源时必须有警示样式。
3. 子任务超时与深度上限 → `partial`/`error` 必须可视化，不得吞掉。
4. 数据缺口显式标注 → 缺口断线 + `缺数` 徽标，禁止插值补点。
5. 全链路 trace 可回溯 → `trace_id` 全局可点可复制，可跳链路页。

**交付物**：
- `apps/admin/` 完整可运行前端工程（Vue 3 + Vite + TS + Element Plus），含 `README.md` 说明启动方式。
- `src/api/` 接口层（真实实现 + stub 实现分离），`src/types/` 与后端 OpenAPI 对齐。
- 各页面按第三节实现，stub 数据页面顶部统一标注「演示数据」。

**验收方式**：后端按第一节命令启动后，逐条跑通 4.3 的 9 个演示场景，并核对每条「可靠性五件套」。

**禁止事项汇总**：
- 禁止伪造或美化业务数据、引用、置信度、缺口。
- 禁止任何绕过人工确认的执行入口。
- 禁止在前端改写后端结论文案的业务含义。
- 禁止把 stub 数据伪装成真实数据。
- 禁止在缺口时段插值连线、跨井型套用指标。
