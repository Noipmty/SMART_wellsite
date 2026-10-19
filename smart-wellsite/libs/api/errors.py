"""统一错误响应体与全局异常处理器。

所有错误均返回同一结构，便于前端与调用方解析：

    {
        "error": {
            "code": "NOT_FOUND",
            "message": "资源不存在",
            "details": {...},            # 可选
            "request_id": "a1b2c3..."
        }
    }
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = structlog.get_logger(__name__)

_HTTP_STATUS_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    429: "TOO_MANY_REQUESTS",
    503: "SERVICE_UNAVAILABLE",
}


class AppError(Exception):
    """业务错误基类：子类通过类属性约定错误码与 HTTP 状态码。"""

    code: str = "INTERNAL_ERROR"
    http_status: int = 400

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        http_status: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details


class BadRequestError(AppError):
    """请求语义错误（400）。"""

    code = "BAD_REQUEST"
    http_status = 400


class NotFoundError(AppError):
    """资源不存在（404）。"""

    code = "NOT_FOUND"
    http_status = 404


class ConflictError(AppError):
    """资源状态冲突（409）。"""

    code = "CONFLICT"
    http_status = 409


class ServiceUnavailableError(AppError):
    """服务暂不可用（503）。"""

    code = "SERVICE_UNAVAILABLE"
    http_status = 503


def _error_body(
    request: Request,
    code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request.scope.get("request_id"),
        }
    }
    if details is not None:
        body["error"]["details"] = details
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器，保证任何路径返回结构一致。"""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info(
            "request.app_error",
            code=exc.code,
            status=exc.http_status,
            path=request.url.path,
            message=exc.message,
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=_error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # errors() 的 ctx 中可能含 ValueError 实例，jsonable_encoder 会安全序列化
        details = jsonable_encoder(exc.errors())
        logger.info(
            "request.validation_error",
            path=request.url.path,
            error_count=len(details),
        )
        return JSONResponse(
            status_code=422,
            content=_error_body(
                request, "VALIDATION_ERROR", "请求参数校验失败", details
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 统一 404/405/413 等框架内 HTTP 错误的响应体结构
        code = _HTTP_STATUS_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code, str(exc.detail)),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # 兜底：未预期异常不外泄堆栈，仅记录日志并返回脱敏信息
        logger.exception("request.unhandled_error", path=request.url.path)
        return JSONResponse(
            status_code=500,
            content=_error_body(request, "INTERNAL_ERROR", "服务内部错误"),
        )
