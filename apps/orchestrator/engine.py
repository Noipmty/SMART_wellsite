"""编排引擎：任务分解、并行执行、deadline 熔断、循环检测、预算控制、结果聚合。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog

from agents.base import BaseAgent
from agents.duty_assistant import DutyAssistantAgent
from agents.orchestrator_agent import OrchestratorAgent, SubtaskSpec
from libs.schemas import AgentName, AgentResult, AgentTask, FinalAnswer, IntentType, StructuredIntent
from sim.points import resolve_metric, spec_by_suffix, tag_for
from sim.registry import WELLS

logger = structlog.get_logger(__name__)

MAX_CALLS = 5          # 单次请求 Agent 调用预算
MAX_SAME_ROUTE = 2     # 同一 task 路由给同一 Agent 的上限（循环检测）
DEFAULT_METRIC = {"oil": "daily_oil_prod", "gas": "daily_gas_prod", "drilling": "rpm"}


class Orchestrator:
    """多智能体编排器。"""

    def __init__(self, agents: dict[AgentName, BaseAgent], duty: DutyAssistantAgent,
                 max_calls: int = MAX_CALLS) -> None:
        self._agents = agents
        self._duty = duty
        self._scheduler = OrchestratorAgent()
        self._max_calls = max_calls

    async def run(self, question: str, session_id: str | None = None,
                  eventbus: Any = None) -> FinalAnswer:
        """完整链路：理解 → 路由 → 并行执行 → 聚合 → 最终回答。"""
        trace_id = f"tr-{uuid.uuid4().hex[:8]}"
        intent = self._duty.understand(question, session_id)
        intent.trace_id = trace_id

        if intent.need_clarify:
            return self._duty.compose(question, intent, [], [], trace_id, session_id)

        specs = self._scheduler.route(intent)
        results, conflicts = await self._execute(specs, intent, trace_id)

        # 诊断结论需复核 / 感知事件 → 追加告警处置
        alerts = self._derive_alerts(results)
        if alerts:
            if len(results) + 1 > self._max_calls:
                conflicts.append(f"调用预算 {self._max_calls} 次已上限，告警处置未执行")
            else:
                handler = self._agents.get(AgentName.ALERT_HANDLER)
                if handler is not None:
                    r = await self._run_one(
                        SubtaskSpec(AgentName.ALERT_HANDLER, 8000, "告警处置"),
                        intent, trace_id, {"alerts": alerts},
                    )
                    if r is not None:
                        results.append(r)

        if eventbus is not None:
            await self._publish(eventbus, results, trace_id)

        return self._duty.compose(question, intent, results, conflicts, trace_id, session_id)

    # ---------------- 执行 ----------------

    async def _execute(self, specs: list[SubtaskSpec], intent: StructuredIntent,
                       trace_id: str) -> tuple[list[AgentResult], list[str]]:
        conflicts: list[str] = []
        route_count: dict[tuple[str, str], int] = {}

        selected: list[SubtaskSpec] = []
        for sp in specs:
            key = (sp.agent.value, intent.entities.well or "")
            route_count[key] = route_count.get(key, 0) + 1
            if route_count[key] > MAX_SAME_ROUTE:
                conflicts.append(f"检测到循环：{sp.agent.value} 重复路由超过 {MAX_SAME_ROUTE} 次，已终止该分支")
                continue
            selected.append(sp)

        if len(selected) > self._max_calls:
            conflicts.append(f"调用预算 {self._max_calls} 次已上限，超出部分未执行")
            selected = selected[: self._max_calls]

        if not selected:
            return [], conflicts

        gathered = await asyncio.gather(*[self._run_one(sp, intent, trace_id) for sp in selected])
        results = [r for r in gathered if r is not None]

        results.extend(await self._review_if_needed(results, intent))
        conflicts.extend(self._detect_conflicts(results))
        return results, conflicts

    async def _run_one(self, spec: SubtaskSpec, intent: StructuredIntent, trace_id: str,
                       extra: dict[str, Any] | None = None) -> AgentResult | None:
        agent = self._agents.get(spec.agent)
        if agent is None:
            return None
        payload = self._build_payload(spec, intent)
        if extra:
            payload.update(extra)
        task = AgentTask(trace_id=trace_id, to_agent=spec.agent, intent=intent.intent,
                         payload=payload, deadline_ms=spec.deadline_ms)
        try:
            return await asyncio.wait_for(agent.handle(task), timeout=spec.deadline_ms / 1000)
        except asyncio.TimeoutError:
            logger.warning("agent.timeout", agent=spec.agent.value, deadline_ms=spec.deadline_ms)
            return AgentResult(
                agent=spec.agent, trace_id=trace_id, task_id=task.task_id,
                conclusion="子任务超时熔断", partial=True,
                error=f"deadline {spec.deadline_ms}ms 超时", elapsed_ms=spec.deadline_ms,
            )

    def _build_payload(self, spec: SubtaskSpec, intent: StructuredIntent) -> dict[str, Any]:
        p: dict[str, Any] = {
            "well": intent.entities.well,
            "time_range": intent.entities.time,
            "question": intent.question,
        }
        if spec.agent is AgentName.DATA_COLLECTOR:
            p["tag"] = self._resolve_tag(intent)
        if spec.agent is AgentName.REPORT_KNOWLEDGE:
            p["kind"] = "report" if intent.intent is IntentType.REPORT else "knowledge"
        return p

    @staticmethod
    def _resolve_tag(intent: StructuredIntent) -> str:
        well = intent.entities.well
        if not well or well not in WELLS:
            return ""
        wtype = WELLS[well].well_type
        specs = resolve_metric(intent.entities.metric, wtype) if intent.entities.metric else []
        spec = specs[0] if len(specs) == 1 else spec_by_suffix(DEFAULT_METRIC.get(wtype, "daily_oil_prod"))
        return tag_for(spec, well) if spec else ""

    # ---------------- 复核 / 告警 / 冲突 ----------------

    async def _review_if_needed(self, results: list[AgentResult],
                               intent: StructuredIntent) -> list[AgentResult]:
        """诊断结论 needs_review=true → 追加生产分析复核子任务（受调用预算约束）。"""
        diag = next((r for r in results if r.agent is AgentName.DEVICE_DIAGNOSIS), None)
        if not diag or not diag.needs_review:
            return []
        if any(r.agent is AgentName.PRODUCTION_ANALYSIS for r in results):
            return []
        if len(results) + 1 > self._max_calls:
            logger.info("review.skipped.budget", trace_id=intent.trace_id)
            return []
        spec = SubtaskSpec(AgentName.PRODUCTION_ANALYSIS, 8000, "诊断复核")
        r = await self._run_one(spec, intent, intent.trace_id)
        return [r] if r is not None else []

    def _derive_alerts(self, results: list[AgentResult]) -> list[dict[str, Any]]:
        alerts: list[dict[str, Any]] = []
        for r in results:
            if r.agent is AgentName.ENVIRONMENT_SAFETY:
                level = r.data.get("level")
                if level:
                    alerts.append({"level": level, "source": "env_monitor",
                                   "cause": f"{r.data.get('metric', '')} 超阈值",
                                   "content": r.conclusion})
            elif r.agent is AgentName.SAFETY_RISK:
                level = r.data.get("risk_level")
                if level in ("预警", "紧急"):
                    alerts.append({"level": level, "source": "safety_risk",
                                    "cause": r.conclusion, "content": r.conclusion})
            elif r.agent is AgentName.VIDEO_INTELLIGENCE and r.needs_review:
                alerts.append({"level": "紧急", "source": "video_intelligence",
                               "cause": "视频高风险事件", "content": r.conclusion})
        return alerts

    @staticmethod
    def _detect_conflicts(results: list[AgentResult]) -> list[str]:
        """同井同工况的极性冲突检测（结论冲突时并列呈现，不强行合并）。"""
        neg_kw = ("供液不足", "故障", "异常")
        pos_kw = ("正常", "无异常", "无风险")
        neg = [(r.agent.value, r.conclusion) for r in results
               if r.conclusion and any(k in r.conclusion for k in neg_kw)]
        pos = [(r.agent.value, r.conclusion) for r in results
               if r.conclusion and any(k in r.conclusion for k in pos_kw)]
        if neg and pos:
            parts = [f"{a}认为“{c}”" for a, c in neg + pos]
            return ["结论存在分歧，并列呈现：" + "；".join(parts)]
        return []

    @staticmethod
    async def _publish(eventbus: Any, results: list[AgentResult], trace_id: str) -> None:
        for r in results:
            try:
                await eventbus.publish("agent.result", r.model_dump(), trace_id=trace_id)
            except Exception:  # noqa: BLE001
                logger.debug("eventbus.publish.failed", agent=r.agent.value)
