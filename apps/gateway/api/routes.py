"""FastAPI 路由：healthz、chat（多智能体编排）、WebSocket、metrics。"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, WebSocket, WebSocketDisconnect
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field, field_validator

from apps.container import Container
from libs.deterministic import fallback_answer
from libs.schemas import AgentResult, Evidence

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

MESSAGE_MAX_LEN = 2000


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

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("消息内容不能为空")
        if len(value) > MESSAGE_MAX_LEN:
            raise ValueError(f"消息内容不能超过 {MESSAGE_MAX_LEN} 字")
        return value


class ParameterAdviceView(BaseModel):
    """参数调整建议视图（字段名对前端友好）。"""

    param: str
    from_value: float | str | None = Field(default=None, alias="from")
    to_value: float | str | None = Field(default=None, alias="to")
    reason: str = ""
    confirm_required: bool = True
    observe_hours: float | None = None


class AgentResultView(BaseModel):
    """单个节点结论视图（含证据、建议与专属载荷）。"""

    agent: str
    conclusion: str = ""
    confidence: float = 0.0
    confidence_level: str | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    suggestion: str | None = None
    parameter_advice: list[ParameterAdviceView] = Field(default_factory=list)
    needs_review: bool = False
    partial: bool = False
    error: str | None = None
    elapsed_ms: int | None = None
    citations: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


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


def _get_container(request: Request) -> Container | None:
    """获取依赖容器；lifespan 未执行（如部分测试传输）时为 None。"""
    return getattr(request.app.state, "container", None)


def _to_result_view(result: AgentResult) -> AgentResultView:
    """领域结论 → API 视图，枚举统一序列化为值。"""
    return AgentResultView(
        agent=result.agent.value,
        conclusion=result.conclusion,
        confidence=result.confidence,
        confidence_level=(
            result.confidence_level.value if result.confidence_level else None
        ),
        evidence=result.evidence,
        suggestion=result.suggestion,
        parameter_advice=[
            ParameterAdviceView.model_validate(advice.model_dump(by_alias=True))
            for advice in result.parameter_advice
        ],
        needs_review=result.needs_review,
        partial=result.partial,
        error=result.error,
        elapsed_ms=result.elapsed_ms,
        citations=result.citations,
        data=result.data,
    )


@router.get("/healthz", response_model=HealthResponse)
async def healthz(request: Request) -> HealthResponse:
    """健康检查端点。"""
    REQUEST_COUNT.labels(endpoint="/healthz", method="GET").inc()
    container = _get_container(request)
    return HealthResponse(
        services={
            "gateway": "ok",
            "llm": "mock",
            "orchestrator": "ready" if container is not None else "not_ready",
            "agents": "10",
        }
    )


@router.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request) -> ChatResponse:
    """值班助手对话入口：走多智能体编排（理解→路由→协作→聚合）。"""
    REQUEST_COUNT.labels(endpoint="/api/v1/chat", method="POST").inc()
    started = time.monotonic()
    session_id = req.session_id or str(uuid.uuid4())
    container = _get_container(request)

    if container is None:
        logger.warning("chat.orchestrator_not_ready", session_id=session_id)
        return ChatResponse(
            reply=fallback_answer(req.message),
            session_id=session_id,
            partial=True,
            conflicts=["编排器未就绪"],
        )

    try:
        final = await container.orchestrator.run(req.message, session_id)
    except Exception:  # noqa: BLE001 - LLM/链路异常时降级兜底，不向用户抛 5xx
        logger.exception("chat.failed", session_id=session_id)
        elapsed = time.monotonic() - started
        CHAT_LATENCY.observe(elapsed)
        return ChatResponse(
            reply=fallback_answer(req.message),
            session_id=session_id,
            partial=True,
            conflicts=["链路繁忙，已返回规则兜底结论"],
        )

    elapsed = time.monotonic() - started
    CHAT_LATENCY.observe(elapsed)
    logger.info(
        "chat.completed",
        session_id=session_id,
        trace_id=final.trace_id,
        latency_ms=round(elapsed * 1000, 2),
        agents=len(final.results),
    )

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
        results=[_to_result_view(r) for r in final.results],
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 实时推送端点：以单块流式返回编排结果。"""
    await websocket.accept()
    logger.info("ws.connected", client=websocket.client)
    container: Container | None = getattr(websocket.app.state, "container", None)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg_data = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("ws.bad_json", raw=data[:200])
                await websocket.send_text(
                    json.dumps({"type": "error", "content": "消息格式错误，需为 JSON"},
                               ensure_ascii=False)
                )
                continue

            message = str(msg_data.get("message", "")).strip()
            if not message:
                await websocket.send_text(
                    json.dumps({"type": "error", "content": "消息内容不能为空"},
                               ensure_ascii=False)
                )
                continue
            session_id = msg_data.get("session_id") or str(uuid.uuid4())

            if container is None:
                reply = fallback_answer(message)
                meta = {"partial": True, "conflicts": ["编排器未就绪"]}
            else:
                try:
                    final = await container.orchestrator.run(message, session_id)
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

            await websocket.send_text(
                json.dumps({"type": "stream", "content": reply}, ensure_ascii=False)
            )
            await websocket.send_text(
                json.dumps({"type": "done", "reply": reply, **meta},
                           ensure_ascii=False)
            )

    except WebSocketDisconnect:
        logger.info("ws.disconnected")
    except Exception:  # noqa: BLE001
        logger.exception("ws.error")


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus 指标端点。"""
    REQUEST_COUNT.labels(endpoint="/metrics", method="GET").inc()
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
