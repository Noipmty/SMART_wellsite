"""井场只读数据接口：井号台账 / 时序数据 / 事件日历。

数据源为 sim/ mock（等价于 PostgreSQL 设备台账 + TDengine + 人工事件表），
真实部署时仅需替换 sim 绑定，接口契约保持不变。
所有错误走统一错误体，列表走统一分页模型。
"""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from libs.api import (
    BadRequestError,
    NotFoundError,
    Page,
    PageParams,
    pagination_params,
)
from libs.schemas import TelemetryResult
from sim.calendar import events_in_range
from sim.points import spec_by_suffix, split_tag
from sim.registry import WELL_TYPE_CN, WELLS, Well, normalize_well
from sim.scada import parse_dt, query_series
from sim.timebase import at

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["wellsite-data"])

MAX_RANGE_DAYS = 31


class WellView(BaseModel):
    """井号台账视图。"""

    well_id: str
    name: str
    well_type: str
    well_type_cn: str
    device_id: str
    device_type: str
    location: str
    status: str


class CalendarEventView(BaseModel):
    """事件日历条目视图（检修 / 停电 / 限产）。"""

    event_type: str
    wells: list[str]
    start: str
    end: str
    desc: str


def _to_well_view(well: Well) -> WellView:
    return WellView(
        well_id=well.well_id,
        name=well.name,
        well_type=well.well_type,
        well_type_cn=WELL_TYPE_CN.get(well.well_type, well.well_type),
        device_id=well.device_id,
        device_type=well.device_type,
        location=well.location,
        status=well.status,
    )


def _parse_ts(value: str, field: str) -> datetime:
    """解析 "YYYY-MM-DD[ HH:MM]"，格式非法抛统一 400。"""
    try:
        return parse_dt(value)
    except ValueError:
        raise BadRequestError(
            f"时间格式非法：{field}={value!r}，期望 YYYY-MM-DD 或 YYYY-MM-DD HH:MM",
            details={"field": field, "value": value},
        ) from None


def _resolve_time_range(
    start: str | None,
    end: str | None,
    start_field: str = "start",
    end_field: str = "end",
) -> tuple[str, str]:
    """缺省取今日全天；校验 start <= end 且跨度不超过上限（防全表扫描）。"""
    start = start or at(0, "00:00")
    end = end or at(0, "23:59")
    t0, t1 = _parse_ts(start, start_field), _parse_ts(end, end_field)
    if t0 > t1:
        raise BadRequestError(
            f"时间范围非法：{start_field} 必须早于 {end_field}",
            details={start_field: start, end_field: end},
        )
    if (t1 - t0).days > MAX_RANGE_DAYS:
        raise BadRequestError(
            f"时间跨度过大：单次查询最多 {MAX_RANGE_DAYS} 天",
            details={"max_range_days": MAX_RANGE_DAYS},
        )
    return start, end


@router.get("/wells", response_model=Page[WellView])
async def list_wells(
    params: PageParams = Depends(pagination_params),
    well_type: str | None = Query(None, description="按井型过滤：oil / gas / drilling"),
) -> Page[WellView]:
    """井号台账列表（分页，可按井型过滤）。"""
    wells = list(WELLS.values())
    if well_type is not None:
        if well_type not in WELL_TYPE_CN:
            raise BadRequestError(
                f"井型非法：{well_type!r}",
                details={"allowed": sorted(WELL_TYPE_CN)},
            )
        wells = [w for w in wells if w.well_type == well_type]
    items = [
        _to_well_view(w)
        for w in wells[params.offset : params.offset + params.limit]
    ]
    return Page.build(items, total=len(wells), params=params)


@router.get("/wells/{well_id}", response_model=WellView)
async def get_well(well_id: str) -> WellView:
    """单井详情（支持 W-3 / w3 / 3号井 等写法）；井号不存在返回 404。"""
    normalized = normalize_well(well_id)
    well = WELLS.get(normalized) if normalized else None
    if well is None:
        raise NotFoundError(f"井号不存在：{well_id}")
    return _to_well_view(well)


@router.get("/telemetry", response_model=TelemetryResult)
async def query_telemetry(
    tag: str = Query(..., description="测点 tag，如 W3.daily_oil_prod"),
    start: str | None = Query(None, description="起始时间，缺省今日 00:00"),
    end: str | None = Query(None, description="结束时间，缺省今日 23:59"),
) -> TelemetryResult:
    """时序数据查询：透传 series / quality.gap 数据缺口 / 趋势事件。"""
    well_id, suffix = split_tag(tag)
    if not well_id or well_id not in WELLS:
        raise BadRequestError(f"tag 非法或井号不存在：{tag!r}")
    if spec_by_suffix(suffix) is None:
        raise BadRequestError(f"tag 指标未在点表登记：{tag!r}")
    start, end = _resolve_time_range(start, end)
    logger.info("telemetry.query", tag=tag, start=start, end=end)
    return query_series(tag, start, end)


@router.get("/events/calendar", response_model=Page[CalendarEventView])
async def event_calendar(
    params: PageParams = Depends(pagination_params),
    from_: str | None = Query(None, alias="from", description="起始时间，缺省今日 00:00"),
    to: str | None = Query(None, description="结束时间，缺省今日 23:59"),
    well_id: str | None = Query(None, description="按井号过滤"),
) -> Page[CalendarEventView]:
    """事件日历查询：返回与时间窗相交的检修 / 停电 / 限产条目。"""
    start, end = _resolve_time_range(from_, to, "from", "to")
    normalized: str | None = None
    if well_id:
        normalized = normalize_well(well_id)
        if normalized is None:
            raise BadRequestError(f"井号非法：{well_id!r}")
    hits = events_in_range(normalized, start, end)
    items = [
        CalendarEventView(
            event_type=ev.event_type,
            wells=list(ev.wells),
            start=ev.start,
            end=ev.end,
            desc=ev.desc,
        )
        for ev in hits[params.offset : params.offset + params.limit]
    ]
    return Page.build(items, total=len(hits), params=params)
