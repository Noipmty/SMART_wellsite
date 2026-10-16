"""链路追踪查询 API：trace 列表（分页/过滤）与详情（全量节点结论）。

列表返回轻量摘要（不含 results 全量载荷），详情返回完整 TraceRecord，
节点结论中的 evidence/suggestion/parameter_advice/data 已结构化，
供前端追踪页回溯每次请求的推理链路。
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from apps.container import Container
from libs.api import (
    BadRequestError,
    NotFoundError,
    Page,
    PageParams,
    ServiceUnavailableError,
    pagination_params,
)
from libs.schemas.trace import TraceRecord

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["traces"])

MAX_RANGE_DAYS = 31


def _get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise ServiceUnavailableError("服务未就绪")
    return container


def _parse_ts(value: str, field: str) -> datetime:
    """解析 ISO 8601（支持空格分隔、省略秒）；无时区按 UTC 处理。"""
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise BadRequestError(
            f"时间格式非法：{field}={value!r}，"
            "期望 ISO 8601（如 2026-10-16 或 2026-10-16T08:00:00）",
            details={"field": field, "value": value},
        ) from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_window(
    start: str | None, end: str | None
) -> tuple[datetime | None, datetime | None]:
    """解析可选时间窗；校验 start <= end 且跨度不超过上限。"""
    t0 = _parse_ts(start, "start") if start else None
    t1 = _parse_ts(end, "end") if end else None
    if t0 and t1:
        if t0 > t1:
            raise BadRequestError(
                "时间范围非法：start 必须早于 end",
                details={"start": start, "end": end},
            )
        if (t1 - t0).days > MAX_RANGE_DAYS:
            raise BadRequestError(
                f"时间跨度过大：单次查询最多 {MAX_RANGE_DAYS} 天",
                details={"max_range_days": MAX_RANGE_DAYS},
            )
    return t0, t1


class TraceSummary(BaseModel):
    """列表视图：不含 results 全量载荷，控制响应体大小。"""

    trace_id: str
    session_id: str | None = None
    question: str
    intent: str
    need_clarify: bool
    agents: list[str]
    conflicts: list[str]
    partial: bool
    duration_ms: int
    created_at: datetime
    result_count: int = Field(ge=0)

    @classmethod
    def from_record(cls, r: TraceRecord) -> "TraceSummary":
        return cls(
            trace_id=r.trace_id,
            session_id=r.session_id,
            question=r.question,
            intent=r.intent,
            need_clarify=r.need_clarify,
            agents=r.agents,
            conflicts=r.conflicts,
            partial=r.partial,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
            result_count=len(r.results),
        )


@router.get("/traces", response_model=Page[TraceSummary])
async def list_traces(
    request: Request,
    params: PageParams = Depends(pagination_params),
    session_id: str | None = Query(None, description="按会话过滤"),
    intent: str | None = Query(None, description="按意图过滤"),
    start: str | None = Query(None, description="起始时间（ISO 8601，缺省不限）"),
    end: str | None = Query(None, description="结束时间（ISO 8601，缺省不限）"),
) -> Page[TraceSummary]:
    """链路追踪列表（按创建时间倒序，分页）。"""
    container = _get_container(request)
    t0, t1 = _parse_window(start, end)
    records = await container.trace_repo.query(
        session_id=session_id, intent=intent, start=t0, end=t1
    )
    items = [
        TraceSummary.from_record(r)
        for r in records[params.offset : params.offset + params.limit]
    ]
    logger.info("traces.listed", total=len(records),
                session_id=session_id, intent=intent)
    return Page.build(items, total=len(records), params=params)


@router.get("/traces/{trace_id}", response_model=TraceRecord)
async def get_trace(trace_id: str, request: Request) -> TraceRecord:
    """链路详情：全量节点结论（含 evidence / suggestion / data 结构化载荷）。"""
    container = _get_container(request)
    record = await container.trace_repo.get(trace_id)
    if record is None:
        raise NotFoundError(f"链路不存在：{trace_id}")
    return record
