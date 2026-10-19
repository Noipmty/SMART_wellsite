"""告警与工单领域模型（执行层闭环）。

告警状态机：active → acknowledged → resolved
工单状态机：pending → processing → resolved → closed
非法流转由服务层拒绝（409 Conflict），模型本身只做数据载体。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AlertStatus(str, Enum):
    """告警状态。"""

    ACTIVE = "active"                # 待确认
    ACKNOWLEDGED = "acknowledged"    # 已确认
    RESOLVED = "resolved"            # 已关闭


class WorkOrderStatus(str, Enum):
    """工单状态。"""

    PENDING = "pending"          # 待确认
    PROCESSING = "processing"    # 处理中
    RESOLVED = "resolved"        # 已完成
    CLOSED = "closed"            # 已关闭


class EscalationRecord(BaseModel):
    """一次升级记录（去重命中升级 / 超时升级）。"""

    ts: datetime = Field(default_factory=_utcnow)
    kind: str                    # dedup / timeout
    from_level: str
    to_level: str
    notified: list[str] = Field(default_factory=list)
    note: str = ""


class Alert(BaseModel):
    """告警记录（持久化实体）。"""

    alert_id: str = Field(default_factory=lambda: _uid("alt"))
    dedup_key: str = ""
    level: str
    source: str
    cause: str
    scope: str = ""              # 井号 / 区域
    content: str = ""
    status: AlertStatus = AlertStatus.ACTIVE
    hit_count: int = 1           # 去重窗口内同源同因命中次数
    suppressed_count: int = 0    # 被去重抑制的重复通知次数
    first_seen: datetime = Field(default_factory=_utcnow)
    last_seen: datetime = Field(default_factory=_utcnow)
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    resolved_by: str | None = None
    resolved_at: datetime | None = None
    resolution: str | None = None
    escalations: list[EscalationRecord] = Field(default_factory=list)
    trace_id: str = ""


class WorkOrder(BaseModel):
    """工单记录（预警 / 紧急告警自动生成，人工闭环）。"""

    order_id: str = Field(default_factory=lambda: _uid("ord"))
    alert_id: str
    title: str
    priority: str                # 预警 / 紧急
    device_id: str = ""
    well_id: str = ""
    status: WorkOrderStatus = WorkOrderStatus.PENDING
    assignee: str | None = None
    actions_taken: str | None = None
    resolution: str | None = None
    actual_cause: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    escalations: list[EscalationRecord] = Field(default_factory=list)
