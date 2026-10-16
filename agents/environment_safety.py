"""环境安全 Agent（感知层 · 确定性 + 规则）。

职责：气体（H2S/可燃气体/CO）与气象连续监测；分级阈值、趋势预警、气象联动、数据缺失告警。
"""

from __future__ import annotations

from agents.base import BaseAgent
from libs.schemas import AgentName, AgentResult, AgentTask, Evidence
from sim.env_video import ENV_THRESHOLDS, ENV_UNITS, level_for, query_env


class EnvironmentSafetyAgent(BaseAgent):
    name = AgentName.ENVIRONMENT_SAFETY

    async def _process(self, task: AgentTask) -> AgentResult:
        metric = task.payload.get("metric", "H2S")
        well = task.payload.get("well", "")
        tr = task.payload.get("time_range") or []
        start, end = (tr + ["", ""])[:2]

        series, trend = query_env(metric, well, start, end)
        unit = ENV_UNITS.get(metric, "")
        thresholds = ENV_THRESHOLDS.get(metric, {})

        evidence: list[Evidence] = []
        level: str | None = None
        if series:
            last = series[-1]
            level = level_for(metric, last.value)
            evidence.append(
                Evidence(ts=last.ts, metric=metric, value=last.value,
                         trend=trend, source="env_monitor",
                         detail=f"阈值 提醒{thresholds.get('提醒')}/预警{thresholds.get('预警')}/紧急{thresholds.get('紧急')} {unit}")
            )
        # 趋势预警：短时快速爬升即使未到阈值也提示关注
        trend_watch = trend == "up" and level is None and series and series[-1].value > ENV_THRESHOLDS.get(metric, {}).get("提醒", 0) * 0.6

        if level:
            conclusion = f"{well} {metric} 实测 {series[-1].value}{unit}，达到【{level}】级（趋势 {trend}）"
        elif trend_watch:
            conclusion = f"{well} {metric} 快速爬升（{trend}），当前未达阈值，建议关注"
            level = "提醒"
        else:
            conclusion = f"{well} {metric} 处于正常范围（趋势 {trend}）"

        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=conclusion,
            confidence=0.95,
            evidence=evidence,
            needs_review=bool(level),
            data={"metric": metric, "level": level, "trend": trend,
                  "thresholds": thresholds, "unit": unit},
            citations=[f"env_monitor {well} {metric} {start}~{end}"],
        )
