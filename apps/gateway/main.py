"""FastAPI 网关主应用：/healthz、/api/v1/chat、WebSocket 实时推送。

值班助手入口，请求交给编排器（apps.orchestrator）完成多智能体协作。
依赖通过 lifespan 装配到 ``app.state.container``，路由层按需取用。
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.container import Container
from configs import get_settings
from libs.api import RequestIDMiddleware, register_exception_handlers
from libs.tracing import setup_observability

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：装配依赖容器 / 释放资源。"""
    setup_observability()
    logger.info("gateway.starting")

    container = await Container.create()
    app.state.container = container

    logger.info("gateway.ready", port=get_settings().gateway_port)
    try:
        yield
    finally:
        await container.shutdown()
        app.state.container = None
        logger.info("gateway.stopped")


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    settings = get_settings()
    origins = settings.cors_origin_list

    app = FastAPI(
        title="智慧井场多智能体系统",
        description="五层架构·10 Agent·3 阶段落地·LangGraph + FastAPI",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS：显式来源才允许携带凭证；"*" 时不允许凭证（浏览器安全约束）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=origins != ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # 请求 ID 注入 + structlog 上下文 + 访问日志
    app.add_middleware(RequestIDMiddleware)

    # 统一错误响应体
    register_exception_handlers(app)

    # 注册路由
    from apps.gateway.api.alerts import router as alerts_router
    from apps.gateway.api.routes import router
    from apps.gateway.api.wellsite import router as wellsite_router

    app.include_router(router)
    app.include_router(wellsite_router)
    app.include_router(alerts_router)

    return app


app = create_app()
