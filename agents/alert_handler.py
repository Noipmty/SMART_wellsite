"""告警处置 Agent（执行层 · 确定性 + 规则）。

职责：把编排链路派生的告警事件交给 AlertService 完成
持久化、去重聚合、分级通知与工单闭环；Agent 只做薄适配。
旁路保障：不替代现场原报警链路。
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from libs.schemas import AgentName, AgentResult, AgentTask, Level
from services.alert_service import CHANNEL_MAP, AlertService


def _level_text(level: Level | str) -> str:
    """把 Level 枚举/字符串统一渲染为中文等级。"""
    return level.value if hasattr(level, "value") else str(level)


class AlertHandlerAgent(BaseAgent):
    name = AgentName.ALERT_HANDLER

    def __init__(self, alert_service: AlertService) -> None:
        self._service = alert_service

    async def _process(self, task: AgentTask) -> AgentResult:
        alerts: list[dict[str, Any]] = task.payload.get("alerts", [])
        if isinstance(alerts, dict):
            alerts = [alerts]

        handled: list[dict[str, Any]] = []
        for a in alerts:
            level = a.get("level", Level.WATCH.value)
            alert, created = await self._service.ingest(
                source=a.get("source", "unknown"),
                cause=a.get("cause", a.get("title", "")),
                level=level,
                scope=a.get("well", "") or a.get("scope", ""),
                content=a.get("content", ""),
                trace_id=task.trace_id,
            )
            channels, targets = CHANNEL_MAP.get(alert.level, CHANNEL_MAP[Level.WATCH.value])
            handled.append({
                "alert_id": alert.alert_id,
                "dedup_key": alert.dedup_key,
                "level": alert.level,
                "created": created,
                "hit_count": alert.hit_count,
                "channels": channels,
                "targets": targets,
                "content": alert.content,
            })

        summary = (
            "；".join(
                f"{_level_text(h['level'])}级 {h['content']} → 通知 {','.join(h['targets'])}"
                + ("" if h["created"] else f"（去重命中第 {h['hit_count']} 次）")
                for h in handled
            )
            if handled
            else "无告警需处置"
        )
        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=f"已处置 {len(handled)} 条告警"
                       f"（新建 {sum(1 for h in handled if h['created'])} 条）",
            confidence=1.0,
            suggestion=summary,
            data={"handled": handled},
        )
