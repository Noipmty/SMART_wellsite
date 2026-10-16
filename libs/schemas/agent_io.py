"""LLM Agent 结构化输出模型（function calling / JSON mode 的 target schema）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from libs.schemas.enums import AgentName, IntentType, Level
from libs.schemas.messages import Evidence, ParameterAdvice


class DiagnosisOutput(BaseModel):
    """设备诊断 Agent 输出（3.6）。"""

    diagnosis: str = Field(description="候选故障假设")
    confidence: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str = ""
    needs_review: bool = False
    known_event: str | None = Field(default=None, description="命中事件日历的人工事件说明")


class ProductionOutput(BaseModel):
    """生产分析 Agent 输出（3.7）。"""

    conclusion: str = ""
    confidence: float = 0.0
    evidence: list[Evidence] = Field(default_factory=list)
    parameter_advice: list[ParameterAdvice] = Field(default_factory=list)


class RiskOutput(BaseModel):
    """安全风险 Agent 输出（3.8）。"""

    risk_level: Level
    description: str = ""
    affected_area: str = ""
    action_suggestion: str = ""
    must_human_confirm: bool = True


class ReportKnowledgeOutput(BaseModel):
    """报表知识 Agent 输出（3.10）。"""

    answer: str = ""
    source_refs: list[str] = Field(default_factory=list)
    report: str | None = None


class RoutingItem(BaseModel):
    """编排层单个子任务。"""

    agent: AgentName
    intent: IntentType | None = None
    reason: str = ""


class RoutingOutput(BaseModel):
    """井场调度 Agent 的任务分解输出（3.2）。"""

    subtasks: list[RoutingItem] = Field(default_factory=list)
    needs_review: bool = False
