"""请求 ID 中间件。

- 透传上游 X-Request-ID（缺失时生成）
- 响应头回写 X-Request-ID，便于端到端排障
- 绑定 structlog 上下文变量，本请求所有日志自动携带 request_id
- 输出统一访问日志（方法/路径/状态码/耗时）
"""

from __future__ import annotations

import time
import uuid

import structlog
from starlette.types import ASGIApp, Receive, Scope, Send

logger = structlog.get_logger(__name__)

REQUEST_ID_HEADER = b"x-request-id"
_MAX_REQUEST_ID_LEN = 64


class RequestIDMiddleware:
    """纯 ASGI 中间件，对 HTTP 请求注入请求 ID。"""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = self._extract_request_id(scope)
        scope["request_id"] = request_id
        structlog.contextvars.bind_contextvars(request_id=request_id)

        started = time.monotonic()
        status_code = 500

        async def send_wrapper(message: dict) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message["headers"].append(
                    (REQUEST_ID_HEADER, request_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self._app(scope, receive, send_wrapper)
        finally:
            latency_ms = round((time.monotonic() - started) * 1000, 2)
            logger.info(
                "http.access",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status_code,
                latency_ms=latency_ms,
            )
            structlog.contextvars.clear_contextvars()

    @staticmethod
    def _extract_request_id(scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name != REQUEST_ID_HEADER:
                continue
            raw = value.decode("latin-1", errors="ignore").strip()
            if not raw:
                break
            # 仅保留白名单字符，防止日志/响应头注入
            safe = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")
            if safe and len(safe) <= _MAX_REQUEST_ID_LEN:
                return safe
            break
        return uuid.uuid4().hex
