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
from repositories.graph_repo import GraphRepository
from repositories.kb_repo import (
    KBCandidateRepository,
    KBChunkRepository,
    KBDocumentRepository,
)
from repositories.trace_repo import TraceRepository
from services.alert_service import AlertService
from services.graph_service import GraphService
from services.kb_service import KBService
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
    kb_doc_repo: KBDocumentRepository
    kb_chunk_repo: KBChunkRepository
    kb_candidate_repo: KBCandidateRepository
    kb_service: KBService
    graph_repo: GraphRepository
    graph_service: GraphService
    orchestrator: Orchestrator

    @classmethod
    async def create(cls) -> "Container":
        """初始化全部基础设施与领域服务。"""
        from configs import get_settings

        settings = get_settings()
        eventbus = create_eventbus()
        await eventbus.start()

        llm_client = MockLLMClient()

        # ---- 仓储装配：memory=内存/mock 语义；pg=PostgreSQL 持久化 ----
        pg_pool = None
        if settings.repo_backend == "pg":
            from libs.db import get_pg_pool
            from repositories.pg import PgRepositories, run_ddl
            from repositories.pg.seed import seed_alerts_orders, seed_extra_kb_docs

            pg_pool = await get_pg_pool()
            await run_ddl(pg_pool)
            repos = PgRepositories(pg_pool)
            trace_repo = repos.trace_repo
            alert_repo = repos.alert_repo
            order_repo = repos.order_repo
            kb_doc_repo = repos.kb_doc_repo
            kb_chunk_repo = repos.kb_chunk_repo
            kb_candidate_repo = repos.kb_candidate_repo
            graph_repo = repos.graph_repo
        else:
            trace_repo = TraceRepository()
            alert_repo = AlertRepository()
            order_repo = WorkOrderRepository()
            kb_doc_repo = KBDocumentRepository()
            kb_chunk_repo = KBChunkRepository()
            kb_candidate_repo = KBCandidateRepository()
            graph_repo = GraphRepository()

        trace_recorder = TraceRecorder(trace_repo)

        alert_service = AlertService(alert_repo, order_repo)
        await alert_service.start_sweeper()

        kb_service = KBService(kb_doc_repo, kb_chunk_repo, kb_candidate_repo)
        await kb_service.seed_defaults()
        alert_service.set_kb_service(kb_service)  # 启用经验自进化沉淀钩子

        if settings.repo_backend == "pg":
            await seed_alerts_orders(alert_repo, order_repo, kb_candidate_repo)
            await seed_extra_kb_docs(kb_service)

        graph_service = GraphService(graph_repo, kb_doc_repo, kb_chunk_repo)
        await graph_service.rebuild(background=False)  # 启动即基于种子 KB 建图

        orchestrator = build_orchestrator(
            llm_client, trace_recorder=trace_recorder,
            alert_service=alert_service, kb_service=kb_service,
        )

        logger.info("container.created", repo_backend=settings.repo_backend)
        return cls(
            eventbus=eventbus,
            llm_client=llm_client,
            trace_repo=trace_repo,
            trace_recorder=trace_recorder,
            alert_repo=alert_repo,
            order_repo=order_repo,
            alert_service=alert_service,
            kb_doc_repo=kb_doc_repo,
            kb_chunk_repo=kb_chunk_repo,
            kb_candidate_repo=kb_candidate_repo,
            kb_service=kb_service,
            graph_repo=graph_repo,
            graph_service=graph_service,
            orchestrator=orchestrator,
        )

    async def shutdown(self) -> None:
        """按依赖反方向释放资源。"""
        await self.alert_service.stop_sweeper()
        await self.eventbus.stop()
        from libs.db import close_connections

        await close_connections()
        logger.info("container.shutdown")
