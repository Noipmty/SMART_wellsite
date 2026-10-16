"""告警处置 Agent（执行层 · 确定性 + 规则）。

职责：分级映射、通知、去重聚合、工单闭环、旁路保障（不替代原报警链路）。
"""

from __future__ import annotations

from agents.base import BaseAgent
from libs.deterministic import AlertDeduplicator
from libs.schemas import AgentName, AgentResult, AgentTask, AlertDecision, Level

# 等级 → 通知渠道 / 目标
CHANNEL_MAP: dict[str, tuple[list[str], list[str]]] = {
    Level.INFO.value: (["值班界面"], ["值班员"]),
    Level.WATCH.value: (["值班界面"], ["值班员"]),
    Level.WARNING.value: (["IM", "短信"], ["值班员"]),
    Level.CRITICAL.value: (["电话", "短信", "声光"], ["值班员", "值班班长"]),
}

# 全局去重聚合器（同源同因 10 分钟聚合）
_DEDUP = AlertDeduplicator(window_minutes=10)


def _level_text(level: Level | str) -> str:
    """把 Level 枚举/字符串统一渲染为中文等级。"""
    return level.value if hasattr(level, "value") else str(level)


class AlertHandlerAgent(BaseAgent):
    name = AgentName.ALERT_HANDLER

    async def _process(self, task: AgentTask) -> AgentResult:
        alerts = task.payload.get("alerts", [])
        if isinstance(alerts, dict):
            alerts = [alerts]

        decisions: list[AlertDecision] = []
        escalated: list[str] = []
        for a in alerts:
            level = a.get("level", Level.WATCH.value)
            source = a.get("source", "unknown")
            cause = a.get("cause", a.get("title", ""))
            scope = a.get("well", "") or a.get("scope", "")

            outcome = _DEDUP.aggregate(source, cause, level, scope)
            channels, targets = CHANNEL_MAP.get(level, CHANNEL_MAP[Level.WATCH.value])

            decision = AlertDecision(
                level=level,
                channels=channels,
                targets=targets,
                content=a.get("content", cause),
                trace_id=task.trace_id,
                dedup_group=outcome.dedup_key,
            )
            # 工单闭环：预警 / 紧急生成工单，人工确认后更新状态
            if level in (Level.WARNING.value, Level.CRITICAL.value):
                decision.order = {"id": f"ORD-{abs(hash(outcome.dedup_key)) % 10000:04d}",
                                   "status": "待确认", "created_from": decision.alert_id}
            if outcome.escalated:
                escalated.append(cause)
            decisions.append(decision)

        summary = (
            "；".join(
                f"{_level_text(d.level)}级 {d.content} → 通知 {','.join(d.targets)}"
                + ("（已升级）" if d.dedup_group in escalated else "")
                for d in decisions
            )
            if decisions
            else "无告警需处置"
        )
        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=f"已分派 {len(decisions)} 条告警通知",
            confidence=1.0,
            suggestion=summary,
            data={"decisions": [d.model_dump(mode="json") for d in decisions]},
        )
