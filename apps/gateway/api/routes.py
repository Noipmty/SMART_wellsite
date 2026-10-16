"""FastAPI 路由：healthz、chat、WebSocket、metrics。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from apps.gateway.main import _llm_client
from libs.llm import LLMMessage, MockLLMClient

logger = structlog.get_logger(__name__)

router = APIRouter()

# Prometheus 指标
REQUEST_COUNT = Counter(
    "wellsite_gateway_requests_total",
    "网关请求总数",
    ["endpoint", "method"],
)
CHAT_LATENCY = Histogram(
    "wellsite_chat_latency_seconds",
    "值班助手对话延迟",
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
)


class HealthResponse(BaseModel):
    """健康检查响应。"""

    status: str = "ok"
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = "0.1.0"
    services: dict[str, str] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    """值班助手对话请求。"""

    message: str = Field(description="用户消息")
    session_id: str | None = Field(default=None, description="会话 ID")
    context: dict[str, Any] = Field(default_factory=dict, description="上下文")


class ChatResponse(BaseModel):
    """值班助手对话响应。"""

    reply: str
    session_id: str
    tools_called: list[str] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """健康检查端点。"""
    REQUEST_COUNT.labels(endpoint="/healthz", method="GET").inc()
    return HealthResponse(
        services={
            "gateway": "ok",
            "llm": "mock",
        }
    )


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """值班助手对话入口（当前返回 Mock 响应）。"""
    REQUEST_COUNT.labels(endpoint="/api/v1/chat", method="POST").inc()

    import time
    start = time.monotonic()

    session_id = req.session_id or str(__import__("uuid").uuid4())

    # 构造消息
    messages = [
        LLMMessage(role="system", content="你是智慧井场值班助手，帮助值班员管理井场设备。"),
        LLMMessage(role="user", content=req.message),
    ]

    # 调用 LLM（未初始化时使用 MockLLMClient）
    llm = _llm_client or MockLLMClient()
    response = await llm.chat(messages)

    elapsed = time.monotonic() - start
    CHAT_LATENCY.observe(elapsed)

    logger.info(
        "chat.completed",
        session_id=session_id,
        latency_ms=round(elapsed * 1000, 2),
    )

    return ChatResponse(
        reply=response.content,
        session_id=session_id,
        tools_called=[],
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 实时推送端点（占位实现）。"""
    await websocket.accept()
    logger.info("ws.connected", client=websocket.client)

    try:
        while True:
            # 接收消息
            data = await websocket.receive_text()
            msg_data = json.loads(data)

            # 构造 LLM 消息
            messages = [
                LLMMessage(role="system", content="你是智慧井场值班助手。"),
                LLMMessage(role="user", content=msg_data.get("message", "")),
            ]

            # 流式输出
            llm = _llm_client or MockLLMClient()
            reply_text = ""
            async for chunk in llm.stream_chat(messages):
                reply_text += chunk
                await websocket.send_text(json.dumps(
                    {"type": "stream", "content": chunk},
                    ensure_ascii=False,
                ))

            # 发送完成信号
            await websocket.send_text(json.dumps(
                {"type": "done", "reply": reply_text},
                ensure_ascii=False,
            ))

    except WebSocketDisconnect:
        logger.info("ws.disconnected")
    except Exception:
        logger.exception("ws.error")


@router.get("/metrics")
async def metrics():
    """Prometheus 指标端点。"""
    from fastapi import Response

    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
