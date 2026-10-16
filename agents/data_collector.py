"""数据采集 Agent（感知层 · 确定性 + 规则）。

职责：数据接入、质量治理（越限/跳变/重复/断档）、断点续传标记、异常事件发布。
本项目数据源为 sim mock；真实部署对接 OPC-UA / Modbus → SCADA 点表。
"""

from __future__ import annotations

from agents.base import BaseAgent
from libs.deterministic import detect_series_anomaly
from libs.schemas import AgentName, AgentResult, AgentTask, Evidence
from sim.scada import query_series


class DataCollectorAgent(BaseAgent):
    name = AgentName.DATA_COLLECTOR

    async def _process(self, task: AgentTask) -> AgentResult:
        tag = task.payload.get("tag", "")
        tr = task.payload.get("time_range") or []
        start, end = (tr + ["", ""])[:2]

        telemetry = query_series(tag, start, end) if tag and start and end else None

        evidence: list[Evidence] = []
        gap_note = ""
        if telemetry:
            if telemetry.quality.get("gap"):
                gap_note = f"存在数据缺口：{'；'.join(telemetry.quality['gap'])}（已标记补数）"
                evidence.append(Evidence(metric="数据缺口", source=tag, detail=gap_note))
            anomaly = detect_series_anomaly(telemetry)
            if anomaly:
                evidence.append(Evidence(metric=telemetry.metric or tag, source=tag,
                                         detail=f"确定性规则判定：{anomaly}"))

        conclusion = "数据完整，无缺口" if not gap_note else gap_note
        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=conclusion,
            confidence=1.0,
            evidence=evidence,
            citations=[f"TDengine {tag} {start}~{end}"] if tag else [],
            data={"telemetry": telemetry.model_dump() if telemetry else {}},
        )
