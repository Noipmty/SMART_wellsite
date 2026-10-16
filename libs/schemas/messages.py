"""协作消息 Schema（提示词第四节数据形态）。

① 结构化意图  ② Agent 间任务消息  ③ 工具查询结果
④ 分析结论    ⑤ 最终回答          ⑥ 感知事件
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator

from libs.schemas.enums import AgentName, ConfidenceLevel, IntentType, Level


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Entities(BaseModel):
    """实体抽取结果：well / metric / time / equipment。"""

    well: str | None = None
    metric: str | None = None
    time: list[str] | None = None
    equipment: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class StructuredIntent(BaseModel):
    """① 结构化意图（值班助手 → 调度）。"""

    intent: IntentType
    entities: Entities = Field(default_factory=Entities)
    confidence: float = 0.0
    need_clarify: bool = False
    clarify_options: list[str] = Field(default_factory=list)
    question: str = ""
    trace_id: str = Field(default_factory=lambda: _uid("tr"))
    session_id: str | None = None

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class AgentTask(BaseModel):
    """② Agent 间任务消息（调度 → 各 Agent，走消息总线）。"""

    task_id: str = Field(default_factory=lambda: _uid("t"))
    trace_id: str
    from_agent: AgentName = AgentName.ORCHESTRATOR
    to_agent: AgentName
    intent: IntentType | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    deadline_ms: int = 8000
    created_at: datetime = Field(default_factory=_now)


class Evidence(BaseModel):
    """结论依据（数据来源或知识库条目）。"""

    ts: str | None = None
    metric: str
    value: float | str | None = None
    trend: str | None = None
    source: str | None = None
    detail: str | None = None


class ParameterAdvice(BaseModel):
    """参数调整建议（仅参考，需人工确认）。"""

    param: str
    from_value: float | str | None = Field(default=None, alias="from")
    to_value: float | str | None = Field(default=None, alias="to")
    reason: str = ""
    confirm_required: bool = True
    observe_hours: float | None = None

    model_config = {"populate_by_name": True}


class AgentResult(BaseModel):
    """④ 分析结论（分析 Agent → 调度）。"""

    agent: AgentName
    trace_id: str
    task_id: str | None = None
    conclusion: str = ""
    confidence: float = 0.0
    confidence_level: ConfidenceLevel | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str | None = None
    parameter_advice: list[ParameterAdvice] = Field(default_factory=list)
    needs_review: bool = False
    partial: bool = False
    error: str | None = None
    elapsed_ms: int | None = None
    citations: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict, description="Agent 专属载荷（时序/检测/告警决策等）")


class FinalAnswer(BaseModel):
    """⑤ 最终回答（值班助手 → 用户）。"""

    answer: str
    citations: list[str] = Field(default_factory=list)
    followup: str | None = None
    trace_id: str | None = None
    session_id: str | None = None
    confidence_level: ConfidenceLevel | None = None
    need_clarify: bool = False
    clarify_options: list[str] = Field(default_factory=list)
    results: list[AgentResult] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    partial: bool = False


class PerceptionEvent(BaseModel):
    """⑥ 感知事件（感知层 → 消息总线，供分析层订阅）。"""

    event_id: str = Field(default_factory=lambda: _uid("evt"))
    type: str
    source: AgentName | str
    ts: str
    payload: dict[str, Any] = Field(default_factory=dict)
    level: Level | None = None
    trace_id: str | None = None


class TelemetryPoint(BaseModel):
    ts: str
    value: float


class TelemetryResult(BaseModel):
    """③ 工具查询结果（TDengine 返回；本项目由 sim 提供 mock）。"""

    tag: str
    metric: str | None = None
    unit: str | None = None
    series: list[TelemetryPoint] = Field(default_factory=list)
    quality: dict[str, Any] = Field(default_factory=dict)
    events: list[PerceptionEvent] = Field(default_factory=list)


class AlertDecision(BaseModel):
    """告警处置输出（执行层）。"""

    alert_id: str = Field(default_factory=lambda: _uid("alt"))
    level: Level
    channels: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    content: str = ""
    order: dict[str, Any] | None = None
    trace_id: str = ""
    dedup_group: str | None = None
