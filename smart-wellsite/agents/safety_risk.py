"""安全风险 Agent（分析层 · LLM Agent，提示词 3.8）。

职责：隐患识别、风险分级、应急联动建议。只有建议权，处置动作必须人工确认。
"""

from __future__ import annotations

from agents.base import BaseAgent
from libs.llm.base import LLMClient, LLMMessage
from libs.prompts import SAFETY_RISK, build_system_prompt
from libs.schemas import AgentName, AgentResult, AgentTask, Evidence, RiskOutput
from sim.env_video import ENV_UNITS, level_for, query_env, query_video

_ROLE = "安全风险"
_ENV_METRICS = ("H2S", "可燃气体", "CO")


class SafetyRiskAgent(BaseAgent):
    name = AgentName.SAFETY_RISK

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def _process(self, task: AgentTask) -> AgentResult:
        well = task.payload.get("well", "")
        start, end = (task.payload.get("time_range") or ["", ""])[:2]

        evidence: list[Evidence] = []
        findings: list[str] = []
        for metric in _ENV_METRICS:
            series, trend = query_env(metric, well, start, end)
            if not series:
                continue
            last = series[-1]
            lv = level_for(metric, last.value)
            if lv:
                findings.append(f"{metric} 实测 {last.value}{ENV_UNITS.get(metric, '')}，达到{lv}级")
            evidence.append(Evidence(ts=last.ts, metric=metric, value=last.value,
                                     trend=trend, source="env_monitor"))

        detections = query_video(None, well, start, end)
        for d in detections:
            findings.append(f"{d['cam_id']} 识别到 {d['class']}（置信度 {d['conf']}）")
            evidence.append(Evidence(ts=d["ts"], metric=d["class"], value=round(d["conf"], 2),
                                     source=f"video {d['cam_id']}"))

        user = (
            f"井号：{well}\n时间范围：{start} ~ {end}\n"
            f"监测发现：{'；'.join(findings) if findings else '无异常'}\n"
            "请给出风险分级与应急联动建议（所有处置动作必须 must_human_confirm=true）。"
        )
        out: RiskOutput = await self._llm.chat_with_json(
            messages=[
                LLMMessage(role="system", content=build_system_prompt(_ROLE, SAFETY_RISK)),
                LLMMessage(role="user", content=user),
            ],
            response_model=RiskOutput,
        )

        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=out.description or "无风险",
            confidence=0.9,
            evidence=evidence,
            suggestion=out.action_suggestion,
            needs_review=bool(findings),
            data={
                "risk_level": out.risk_level.value if hasattr(out.risk_level, "value") else str(out.risk_level),
                "affected_area": out.affected_area,
                "must_human_confirm": True,  # 强制人工确认
                "findings": findings,
            },
            citations=[f"env_monitor {well}"] + [f"video {d['cam_id']}" for d in detections],
        )
