"""FastAPI 网关主应用：/healthz、/api/v1/chat、WebSocket 实时推送。

值班助手入口，请求交给编排器（apps.orchestrator）完成多智能体协作。
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from apps.orchestrator import build_orchestrator
from configs import get_settings
from libs.eventbus import create_eventbus
from libs.llm import MockLLMClient, LLMMessage
from libs.tracing import setup_observability

logger = structlog.get_logger(__name__)

# 全局单例
_eventbus = None
_llm_client: MockLLMClient | None = None
_orchestrator: Any = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动 / 关闭。"""
    global _eventbus, _llm_client, _orchestrator

    setup_observability()
    logger.info("gateway.starting")

    # 初始化事件总线
    _eventbus = create_eventbus()
    await _eventbus.start()

    # 初始化 LLM 客户端（mock）
    _llm_client = MockLLMClient()

    # 装配多智能体编排器
    _orchestrator = build_orchestrator(_llm_client)

    logger.info("gateway.ready", port=get_settings().gateway_port)

    yield

    # 关闭
    if _eventbus:
        await _eventbus.stop()
    logger.info("gateway.stopped")


def create_app() -> FastAPI:
    """创建 FastAPI 应用。"""
    app = FastAPI(
        title="智慧井场多智能体系统",
        description="五层架构·10 Agent·3 阶段落地·LangGraph + FastAPI",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from apps.gateway.api.routes import router

    app.include_router(router)

    return app


app = create_app()
