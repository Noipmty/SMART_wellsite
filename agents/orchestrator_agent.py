"""井场调度 Agent（编排层 · LLM Agent，提示词 3.2）。

提供路由规则（与提示词一致）与任务分解；执行层的 deadline / 循环检测 / 预算 / 聚合
由 apps.orchestrator.engine 承担。
"""

from __future__ import annotations

from dataclasses import dataclass

from libs.prompts import ORCHESTRATOR, build_system_prompt
from libs.schemas import AgentName, IntentType, StructuredIntent

_ROLE = "井场调度"

# 默认 deadline（ms）
DEFAULT_DEADLINE = 8000
DIAGNOSIS_DEADLINE = 15000


@dataclass(frozen=True)
class SubtaskSpec:
    """一条待派发子任务。"""

    agent: AgentName
    deadline_ms: int = DEFAULT_DEADLINE
    reason: str = ""


class OrchestratorAgent:
    """井场调度：按路由规则把结构化意图分解为可并行子任务。"""

    name = AgentName.ORCHESTRATOR

    @property
    def system_prompt(self) -> str:
        return build_system_prompt(_ROLE, ORCHESTRATOR)

    def route(self, intent: StructuredIntent) -> list[SubtaskSpec]:
        """按意图（含多意图）生成子任务列表。"""
        intents = self._all_intents(intent)
        specs: list[SubtaskSpec] = []
        for it in intents:
            specs.extend(self._route_one(it))
        # 去重（同一 Agent 只派发一次，取首个 reason）
        seen: dict[AgentName, SubtaskSpec] = {}
        for sp in specs:
            seen.setdefault(sp.agent, sp)
        return list(seen.values())

    @staticmethod
    def _all_intents(intent: StructuredIntent) -> list[IntentType]:
        raw = intent.entities.raw.get("intents") or []
        out: list[IntentType] = []
        for v in raw:
            try:
                out.append(IntentType(v))
            except ValueError:
                continue
        if intent.intent not in out:
            out.append(intent.intent)
        return out

    @staticmethod
    def _route_one(intent_type: IntentType) -> list[SubtaskSpec]:
        if intent_type is IntentType.DIAGNOSIS:
            return [
                SubtaskSpec(AgentName.DEVICE_DIAGNOSIS, DIAGNOSIS_DEADLINE, "设备诊断（异常优先）"),
                SubtaskSpec(AgentName.DATA_COLLECTOR, DEFAULT_DEADLINE, "附带数据查询"),
            ]
        if intent_type is IntentType.PRODUCTION_QUERY:
            return [
                SubtaskSpec(AgentName.DATA_COLLECTOR, DEFAULT_DEADLINE, "生产数据查询"),
                SubtaskSpec(AgentName.PRODUCTION_ANALYSIS, DEFAULT_DEADLINE, "生产分析"),
            ]
        if intent_type is IntentType.PRODUCTION_ANALYSIS:
            return [
                SubtaskSpec(AgentName.PRODUCTION_ANALYSIS, DEFAULT_DEADLINE, "生产分析"),
                SubtaskSpec(AgentName.DATA_COLLECTOR, DEFAULT_DEADLINE, "附带数据查询"),
            ]
        if intent_type is IntentType.RISK:
            return [
                SubtaskSpec(AgentName.SAFETY_RISK, DEFAULT_DEADLINE, "安全风险分级"),
                SubtaskSpec(AgentName.ENVIRONMENT_SAFETY, DEFAULT_DEADLINE, "环境监测"),
                SubtaskSpec(AgentName.VIDEO_INTELLIGENCE, DEFAULT_DEADLINE, "视频智能识别"),
            ]
        if intent_type is IntentType.REPORT:
            return [SubtaskSpec(AgentName.REPORT_KNOWLEDGE, DEFAULT_DEADLINE, "报表生成")]
        if intent_type is IntentType.KNOWLEDGE:
            return [SubtaskSpec(AgentName.REPORT_KNOWLEDGE, DEFAULT_DEADLINE, "知识问答（RAG）")]
        return []  # general：值班助手直接回答，不派发
