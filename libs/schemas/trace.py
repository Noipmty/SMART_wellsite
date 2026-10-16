"""链路追踪领域模型：一次请求经过的全量节点结论。"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from libs.schemas.messages import AgentResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TraceRecord(BaseModel):
    """一次值班助手请求的完整链路记录（全链路 trace 可回溯）。"""

    trace_id: str
    session_id: str | None = None
    question: str
    intent: str
    need_clarify: bool = False
    agents: list[str] = Field(default_factory=list)
    results: list[AgentResult] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    partial: bool = False
    duration_ms: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
