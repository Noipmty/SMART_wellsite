"""安全模块：人工确认、审计日志、工具白名单。"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

# 工具白名单
TOOL_WHITELIST: set[str] = {
    "query_sensor_data",
    "query_indicator_data",
    "query_diagnosis",
    "query_alerts",
    "query_knowledge",
    "query_work_orders",
    "submit_control_request",  # 仅提交请求，不执行
    "acknowledge_alert",
    "close_work_order",
}

# 需要人工确认的动作
CONFIRM_REQUIRED_ACTIONS: set[str] = {
    "stop_well",
    "start_well",
    "adjust_frequency",
    "adjust_parameter",
    "remote_control",
}


class ConfirmRequest(BaseModel):
    """人工确认请求。"""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: str = Field(description="动作类型：stop_well / start_well / adjust_frequency 等")
    target: str = Field(description="目标设备：well_id 或 device_id")
    params: dict[str, Any] = Field(default_factory=dict, description="动作参数")
    reason: str = Field(description="请求原因")
    status: str = Field(default="pending", description="pending / approved / rejected")
    requested_by: str = "agent"
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    confirmed_by: str | None = None
    confirmed_at: datetime | None = None


class AuditLog(BaseModel):
    """审计日志。"""

    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: str
    actor: str
    target: str
    details: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    trace_id: str | None = None


def is_tool_allowed(tool_name: str) -> bool:
    """检查工具是否在白名单中。"""
    return tool_name in TOOL_WHITELIST


def is_confirm_required(action: str) -> bool:
    """检查动作是否需要人工确认。"""
    return action in CONFIRM_REQUIRED_ACTIONS


def create_audit_log(
    action: str,
    actor: str,
    target: str,
    details: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> AuditLog:
    """创建审计日志并记录。"""
    log = AuditLog(
        action=action,
        actor=actor,
        target=target,
        details=details or {},
        trace_id=trace_id,
    )
    logger.info(
        "audit.log",
        log_id=log.log_id,
        action=action,
        actor=actor,
        target=target,
        details=json.dumps(log.details, ensure_ascii=False),
    )
    return log
