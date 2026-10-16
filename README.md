# 智慧井场多智能体系统

> 五层架构 · 10 Agent · 3 阶段落地 · LangGraph + FastAPI · 知识图谱优先 RAG

## 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        交互层 (Interaction)                       │
│          值班助手 (Duty Assistant) · FastAPI + WebSocket           │
├─────────────────────────────────────────────────────────────────┤
│                        编排层 (Orchestration)                     │
│          井场调度编排器 · LangGraph 状态机 · 意图识别+路由         │
├─────────────────────────────────────────────────────────────────┤
│         感知层 (Perception)         │        分析层 (Analysis)      │
│  数据采集 · 视频智能 · 环境安全     │  设备诊断 · 生产分析 · 安全风险 │
├─────────────────────────────────────────────────────────────────┤
│                        执行层 (Execution)                         │
│          告警处置 · 报表知识 · 人工确认 (Human-in-the-loop)        │
├─────────────────────────────────────────────────────────────────┤
│                        数据底座 (Data Layer)                     │
│  TDengine(时序) · PostgreSQL(业务) · Neo4j(图谱) · Milvus(向量)    │
│  事件总线: Redis Stream / MySQL 模拟 · MinIO(对象存储)            │
└─────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
smart-wellsite/
├─ apps/                  # 可部署服务
│  ├─ gateway/            # FastAPI + WebSocket 网关（值班助手入口）
│  ├─ orchestrator/       # LangGraph 编排器
│  └─ admin/              # 值班员审核台
├─ agents/                # 每个 Agent 一个包（graph/tools/schema/prompt）
├─ libs/                  # 公共库
│  ├─ eventbus/           # 事件总线（内存/MySQL模拟/Redis Stream）
│  ├─ db/                 # 数据库连接管理
│  ├─ llm/                # LLM 统一客户端（当前 Mock，预留豆包/DeepSeek）
│  ├─ security/           # 人工确认、审计日志、工具白名单
│  └─ tracing/            # structlog + LangSmith 追踪
├─ sim/                   # 仿真数据源（SCADA/示功图/故障注入）
├─ docker/                # docker-compose 及各服务配置
│  ├─ docker-compose.yml  # 基础设施编排
│  ├─ init/               # 数据库初始化脚本
│  └─ prometheus/         # Prometheus 配置
├─ configs/               # 环境配置（pydantic-settings）
├─ tests/                 # pytest 测试
├─ docs/                  # 文档（架构说明、事件 Topic 清单）
├─ pyproject.toml
├─ .env.example
└─ README.md
```

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 后端框架 | FastAPI + WebSocket | 异步网关，值班助手入口 |
| Agent 编排 | LangGraph | 状态机驱多 Agent 编排 |
| 数据结构 | pydantic v2 | 全部模型定义 |
| 事件总线 | Redis Stream / MySQL 模拟 | 三种实现可切换 |
| 时序数据库 | TDengine 3.3 | 传感器/示功图数据 |
| 业务数据库 | PostgreSQL 15 | 设备/告警/工单 |
| 知识图谱 | Neo4j 5.26 | 阶段二启用 |
| 向量库 | Milvus 2.4 | 阶段二启用 |
| 对象存储 | MinIO | 可选 |
| LLM | Mock（当前）/ 豆包 / DeepSeek | 可配置切换 |
| 追踪 | LangSmith + structlog | 全链路追踪 |
| 监控 | Prometheus + Grafana | 指标 + 看板 |

## 本地启动

### 1. 环境准备

```bash
# 创建 conda 环境
conda create -n zhihui python=3.11 -y
conda activate zhihui

# 安装依赖
cd smart-wellsite
pip install -e ".[dev]"
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，根据需要调整配置
```

### 3. 启动基础设施

```bash
# 启动 Docker 服务（PostgreSQL + TDengine + Redis + MySQL + MinIO）
docker compose -f docker/docker-compose.yml up -d

# 检查服务健康
docker compose -f docker/docker-compose.yml ps
```

### 4. 启动网关

```bash
# 启动 FastAPI 网关
uvicorn apps.gateway.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 验证

```bash
# 健康检查
curl http://localhost:8000/healthz

# 值班助手对话
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "3号井有什么故障？"}'

# 运行测试
pytest
```

## 事件总线

系统支持三种事件总线实现，通过 `EVENTBUS_BACKEND` 配置切换：

| 实现 | 配置值 | 用途 |
|------|--------|------|
| 内存 | `memory` | 单元测试 |
| MySQL 模拟 | `mysql` | 本地开发（无需 Redis） |
| Redis Stream | `redis_stream` | 生产环境 |

Topic 规范：`wellsite/{site_id}/{domain}/{event_type}`

通配符：`*`（单层）`#`（多层）

详见 [事件 Topic 清单](docs/event-topics.md)。

## 落地阶段

| 阶段 | 内容 | Agent |
|------|------|-------|
| P0 | 项目初始化 | — |
| 阶段一 | MVP 5-Agent 闭环 | 采集→诊断→告警→通知 + 编排器 + 值班助手 |
| 阶段二 | 8-Agent 扩展 | 视频/环境/报表 + RAG v1 + 知识图谱 v1 |
| 阶段三 | 10-Agent 完整 | 生产优化 + 安全风险 + 自进化 RAG + 多井扩展 |
| P4 | 收尾 | 可观测/安全/测试/CI-CD/部署 |

## 安全底线

- 远程控制指令必须人工确认（Human-in-the-loop）
- Agent 只有建议权，无执行权
- 工具调用进白名单
- 全程审计日志
