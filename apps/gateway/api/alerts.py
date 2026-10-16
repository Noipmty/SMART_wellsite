"""告警与工单 API：查询、人工确认状态机、工单闭环。

告警状态机：active → acknowledged → resolved（非法流转 409）
工单状态机：pending → processing → resolved → closed
超时升级由容器内 AlertService 后台扫描完成。
"""

from __future__ import annotations

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
from libs.schemas import Level
from libs.schemas.alerts import Alert, AlertStatus, WorkOrder, WorkOrderStatus
from sim.registry import normalize_well

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["alerts"])

_LEVEL_VALUES = {lv.value for lv in Level}


def _get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise ServiceUnavailableError("服务未就绪")
    return container


class OperatorRequest(BaseModel):
    """人工操作请求体（操作人必填，用于审计）。"""

    operator: str = Field(min_length=1, max_length=64)


class ResolveAlertRequest(OperatorRequest):
    resolution: str = Field(min_length=1, max_length=500)


class AssignOrderRequest(OperatorRequest):
    assignee: str = Field(min_length=1, max_length=64)
    actions_taken: str | None = Field(default=None, max_length=500)


class ResolveOrderRequest(OperatorRequest):
    resolution: str = Field(min_length=1, max_length=500)


class CloseOrderRequest(OperatorRequest):
    actual_cause: str = Field(min_length=1, max_length=500)


@router.get("/alerts", response_model=Page[Alert])
async def list_alerts(
    request: Request,
    params: PageParams = Depends(pagination_params),
    status: AlertStatus | None = Query(None, description="按状态过滤"),
    level: str | None = Query(None, description="按等级过滤：提示/提醒/预警/紧急"),
    well_id: str | None = Query(None, description="按井号过滤"),
) -> Page[Alert]:
    """告警列表（按 last_seen 倒序，分页）。"""
    container = _get_container(request)
    if level is not None and level not in _LEVEL_VALUES:
        raise BadRequestError(f"告警等级非法：{level!r}",
                              details={"allowed": sorted(_LEVEL_VALUES)})
    normalized: str | None = None
    if well_id:
        normalized = normalize_well(well_id)
        if normalized is None:
            raise BadRequestError(f"井号非法：{well_id!r}")
    alerts = await container.alert_repo.query(status=status, level=level,
                                              well_id=normalized)
    items = alerts[params.offset : params.offset + params.limit]
    return Page.build(items, total=len(alerts), params=params)


@router.get("/alerts/{alert_id}", response_model=Alert)
async def get_alert(alert_id: str, request: Request) -> Alert:
    """告警详情（含升级记录与去重命中次数）。"""
    container = _get_container(request)
    alert = await container.alert_repo.get_by_id(alert_id)
    if alert is None:
        raise NotFoundError(f"告警不存在：{alert_id}")
    return alert


@router.post("/alerts/{alert_id}/acknowledge", response_model=Alert)
async def acknowledge_alert(alert_id: str, body: OperatorRequest,
                            request: Request) -> Alert:
    """确认告警（active → acknowledged）。"""
    container = _get_container(request)
    return await container.alert_service.acknowledge(alert_id, body.operator)


@router.post("/alerts/{alert_id}/resolve", response_model=Alert)
async def resolve_alert(alert_id: str, body: ResolveAlertRequest,
                        request: Request) -> Alert:
    """关闭告警（active/acknowledged → resolved）。"""
    container = _get_container(request)
    return await container.alert_service.resolve(alert_id, body.operator,
                                                 body.resolution)


@router.get("/workorders", response_model=Page[WorkOrder])
async def list_workorders(
    request: Request,
    params: PageParams = Depends(pagination_params),
    status: WorkOrderStatus | None = Query(None, description="按状态过滤"),
    assignee: str | None = Query(None, description="按处理人过滤"),
) -> Page[WorkOrder]:
    """工单列表（按创建时间倒序，分页）。"""
    container = _get_container(request)
    orders = await container.order_repo.query(status=status, assignee=assignee)
    items = orders[params.offset : params.offset + params.limit]
    return Page.build(items, total=len(orders), params=params)


@router.get("/workorders/{order_id}", response_model=WorkOrder)
async def get_workorder(order_id: str, request: Request) -> WorkOrder:
    """工单详情（含升级督办记录）。"""
    container = _get_container(request)
    order = await container.order_repo.get_by_id(order_id)
    if order is None:
        raise NotFoundError(f"工单不存在：{order_id}")
    return order


@router.post("/workorders/{order_id}/assign", response_model=WorkOrder)
async def assign_workorder(order_id: str, body: AssignOrderRequest,
                           request: Request) -> WorkOrder:
    """接单/指派（pending → processing）。"""
    container = _get_container(request)
    return await container.alert_service.assign_order(
        order_id, body.assignee, body.operator, body.actions_taken
    )


@router.post("/workorders/{order_id}/resolve", response_model=WorkOrder)
async def resolve_workorder(order_id: str, body: ResolveOrderRequest,
                            request: Request) -> WorkOrder:
    """完成工单（processing → resolved）。"""
    container = _get_container(request)
    return await container.alert_service.resolve_order(
        order_id, body.operator, body.resolution
    )


@router.post("/workorders/{order_id}/close", response_model=WorkOrder)
async def close_workorder(order_id: str, body: CloseOrderRequest,
                          request: Request) -> WorkOrder:
    """关闭工单（resolved → closed），回填实际原因形成闭环。"""
    container = _get_container(request)
    return await container.alert_service.close_order(
        order_id, body.operator, body.actual_cause
    )
