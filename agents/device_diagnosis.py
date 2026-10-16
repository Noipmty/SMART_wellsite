"""设备诊断 Agent（分析层 · LLM Agent，提示词 3.6）。

流程：确定性筛异常 → 事件日历排除人工事件 → LLM 给候选故障假设 → 多参数交叉验证。
"""

from __future__ import annotations

import json

from agents._helpers import digest, key_metrics, trend_word
from agents.base import BaseAgent
from libs.llm.base import LLMClient, LLMMessage
from libs.prompts import DEVICE_DIAGNOSIS, build_system_prompt
from libs.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    DiagnosisOutput,
    Evidence,
    to_confidence_level,
)
from sim.calendar import events_in_range

_ROLE = "设备诊断"


class DeviceDiagnosisAgent(BaseAgent):
    name = AgentName.DEVICE_DIAGNOSIS

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

        calendar = events_in_range(well, start, end)
        cal_text = "；".join(f"{c.event_type} {c.start}~{c.end} {c.desc}" for c in calendar) or "无"
        lines = "\n".join(digest(t) for t in metrics)

        user = (
            f"井号：{well}\n时间范围：{start} ~ {end}\n"
            f"关键指标：\n{lines}\n事件日历：{cal_text}\n"
            "请给出候选故障假设（若命中事件日历的人工事件，须直接归因，不得判为设备故障）。"
        )
        out: DiagnosisOutput = await self._llm.chat_with_json(
            messages=[
                LLMMessage(role="system", content=build_system_prompt(_ROLE, DEVICE_DIAGNOSIS)),
                LLMMessage(role="user", content=user),
            ],
            response_model=DiagnosisOutput,
        )

        # 事件日历命中时强制归因人工事件（防因果错误）
        known_event = out.known_event
        if calendar:
            known_event = known_event or calendar[0].desc
            if "检修" in cal_text or "停电" in cal_text or "限产" in cal_text:
                out.diagnosis = f"人工事件导致：{calendar[0].desc}，非设备故障"
                out.needs_review = False

        low_conf = out.confidence < 0.6
        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=out.diagnosis,
            confidence=out.confidence,
            confidence_level=to_confidence_level(out.confidence),
            evidence=evidence,
            suggestion=out.suggestion,
            needs_review=out.needs_review and not low_conf,
            data={"known_event": known_event, "calendar": [c.desc for c in calendar],
                  "low_confidence": low_conf},
            citations=[f"TDengine {t.tag}" for t in metrics],
        )
