"""FastAPI 路由：healthz、chat（多智能体编排）、WebSocket、metrics。"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel, Field

from apps.gateway import main as gateway_main
from libs.deterministic import fallback_answer

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


class AgentResultView(BaseModel):
    """单个节点结论视图。"""

    agent: str
    conclusion: str = ""
    confidence: float = 0.0
    needs_review: bool = False
    partial: bool = False
    error: str | None = None
    elapsed_ms: int | None = None


class ChatResponse(BaseModel):
    """值班助手对话响应。"""

    reply: str
    session_id: str
    trace_id: str = ""
    citations: list[str] = Field(default_factory=list)
    confidence_level: str | None = None
    need_clarify: bool = False
    clarify_options: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    partial: bool = False
    tools_called: list[str] = Field(default_factory=list)
    results: list[AgentResultView] = Field(default_factory=list)
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """健康检查端点。"""
    REQUEST_COUNT.labels(endpoint="/healthz", method="GET").inc()
    return HealthResponse(
        services={
            "gateway": "ok",
            "llm": "mock",
            "orchestrator": "ready" if gateway_main._orchestrator is not None else "not_ready",
            "agents": "10",
        }
    )


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    """值班助手对话入口：走多智能体编排（理解→路由→协作→聚合）。"""
    REQUEST_COUNT.labels(endpoint="/api/v1/chat", method="POST").inc()
    start = time.monotonic()
    session_id = req.session_id or str(uuid.uuid4())
    orchestrator = gateway_main._orchestrator

    if orchestrator is None:
        return ChatResponse(reply=fallback_answer(req.message), session_id=session_id,
                            partial=True, conflicts=["编排器未就绪"])

    try:
        final = await orchestrator.run(req.message, session_id)
    except Exception as exc:  # noqa: BLE001 - LLM/链路异常时降级兜底
        logger.exception("chat.failed", session_id=session_id)
        elapsed = time.monotonic() - start
        CHAT_LATENCY.observe(elapsed)
        return ChatResponse(reply=fallback_answer(req.message), session_id=session_id,
                            partial=True, conflicts=[f"链路异常：{type(exc).__name__}"])

    elapsed = time.monotonic() - start
    CHAT_LATENCY.observe(elapsed)
    logger.info("chat.completed", session_id=session_id, trace_id=final.trace_id,
                latency_ms=round(elapsed * 1000, 2), agents=len(final.results))

    return ChatResponse(
        reply=final.answer,
        session_id=session_id,
        trace_id=final.trace_id or "",
        citations=final.citations,
        confidence_level=final.confidence_level.value if final.confidence_level else None,
        need_clarify=final.need_clarify,
        clarify_options=final.clarify_options,
        conflicts=final.conflicts,
        partial=final.partial,
        tools_called=[r.agent.value for r in final.results],
        results=[
            AgentResultView(
                agent=r.agent.value, conclusion=r.conclusion, confidence=r.confidence,
                needs_review=r.needs_review, partial=r.partial, error=r.error,
                elapsed_ms=r.elapsed_ms,
            )
            for r in final.results
        ],
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 实时推送端点：以单块流式返回编排结果。"""
    await websocket.accept()
    logger.info("ws.connected", client=websocket.client)

    try:
        while True:
            data = await websocket.receive_text()
            msg_data = json.loads(data)
            message = msg_data.get("message", "")
            session_id = msg_data.get("session_id") or str(uuid.uuid4())

            try:
                final = await gateway_main._orchestrator.run(message, session_id)
                reply = final.answer
                meta = {
                    "trace_id": final.trace_id,
                    "citations": final.citations,
                    "conflicts": final.conflicts,
                    "partial": final.partial,
                }
            except Exception:  # noqa: BLE001
                logger.exception("ws.run_failed")
                reply = fallback_answer(message)
                meta = {"partial": True}

            await websocket.send_text(json.dumps({"type": "stream", "content": reply},
                                                 ensure_ascii=False))
            await websocket.send_text(json.dumps({"type": "done", "reply": reply, **meta},
                                                 ensure_ascii=False))

    except WebSocketDisconnect:
        logger.info("ws.disconnected")
    except Exception:
        logger.exception("ws.error")


@router.get("/metrics")
async def metrics():
    """Prometheus 指标端点。"""
    from fastapi import Response

    return Response(content=generate_latest(), media_type="text/plain; version=0.0.4")
