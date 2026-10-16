"""应用依赖容器：集中装配并持有基础设施客户端、仓储、服务与编排器单例。

路由层统一通过 ``request.app.state.container`` 获取依赖，
避免模块级可变全局变量在 import 期被缓存为空。
当前为内存/mock 实现；接入真实中间件时只需在本容器内替换绑定。
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from apps.orchestrator import Orchestrator, build_orchestrator
from libs.eventbus import EventBus, create_eventbus
from libs.llm import MockLLMClient
from libs.llm.base import LLMClient
from repositories.alert_repo import AlertRepository, WorkOrderRepository
from repositories.trace_repo import TraceRepository
from services.alert_service import AlertService
from services.trace_recorder import TraceRecorder

logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class Container:
    """应用级依赖容器（由 lifespan 创建并挂到 app.state.container）。"""

    eventbus: EventBus
    llm_client: LLMClient
    trace_repo: TraceRepository
    trace_recorder: TraceRecorder
    alert_repo: AlertRepository
    order_repo: WorkOrderRepository
    alert_service: AlertService
    orchestrator: Orchestrator

    @classmethod
    async def create(cls) -> "Container":
        """初始化全部基础设施与领域服务。"""
        eventbus = create_eventbus()
        await eventbus.start()

        llm_client = MockLLMClient()

        trace_repo = TraceRepository()
        trace_recorder = TraceRecorder(trace_repo)

        alert_repo = AlertRepository()
        order_repo = WorkOrderRepository()
        alert_service = AlertService(alert_repo, order_repo)
        await alert_service.start_sweeper()

        orchestrator = build_orchestrator(
            llm_client, trace_recorder=trace_recorder, alert_service=alert_service
        )

        logger.info("container.created")
        return cls(
            eventbus=eventbus,
            llm_client=llm_client,
            trace_repo=trace_repo,
            trace_recorder=trace_recorder,
            alert_repo=alert_repo,
            order_repo=order_repo,
            alert_service=alert_service,
            orchestrator=orchestrator,
        )

    async def shutdown(self) -> None:
        """按依赖反方向释放资源。"""
        await self.alert_service.stop_sweeper()
        await self.eventbus.stop()
        logger.info("container.shutdown")
