"""生产分析 Agent（分析层 · LLM Agent，提示词 3.7）。

职责：工况、产量与参数优化分析；参数建议仅作参考，必须标注需人工确认。
"""

from __future__ import annotations

from agents._helpers import digest, key_metrics, trend_word
from agents.base import BaseAgent
from libs.llm.base import LLMClient, LLMMessage
from libs.prompts import PRODUCTION_ANALYSIS, build_system_prompt
from libs.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    Evidence,
    ProductionOutput,
    to_confidence_level,
)

_ROLE = "生产分析"


class ProductionAnalysisAgent(BaseAgent):
    name = AgentName.PRODUCTION_ANALYSIS

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _process(self, task: AgentTask) -> AgentResult:
        well = task.payload.get("well", "")
        start, end = (task.payload.get("time_range") or ["", ""])[:2]
        metrics = key_metrics(well, start, end)

        evidence: list[Evidence] = []
        for t in metrics:
            last = t.series[-1] if t.series else None
            evidence.append(
                Evidence(ts=last.ts if last else None, metric=t.metric,
                         value=last.value if last else None, trend=trend_word(t), source=t.tag)
            )
        lines = "\n".join(digest(t) for t in metrics)

        user = (
            f"井号：{well}\n时间范围：{start} ~ {end}\n关键指标：\n{lines}\n"
            "请区分自然波动与异常变化，做多参数交叉验证，给出结论与参数建议（须标注需人工确认）。"
        )
        out: ProductionOutput = await self._llm.chat_with_json(
            messages=[
                LLMMessage(role="system", content=build_system_prompt(_ROLE, PRODUCTION_ANALYSIS)),
                LLMMessage(role="user", content=user),
            ],
            response_model=ProductionOutput,
        )

        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=out.conclusion,
            confidence=out.confidence,
            confidence_level=to_confidence_level(out.confidence),
            evidence=evidence,
            parameter_advice=out.parameter_advice,
            needs_review=True,
            citations=[f"TDengine {t.tag}" for t in metrics],
        )
