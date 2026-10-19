"""HTTP API 公共设施：统一错误体、分页模型、请求 ID 中间件。"""

from libs.api.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    register_exception_handlers,
)
from libs.api.middleware import RequestIDMiddleware
from libs.api.pagination import (
    MAX_PAGE_SIZE,
    Page,
    PageParams,
    pagination_params,
)

__all__ = [
    "AppError",
    "BadRequestError",
    "ConflictError",
    "NotFoundError",
    "ServiceUnavailableError",
    "register_exception_handlers",
    "RequestIDMiddleware",
    "Page",
    "PageParams",
    "MAX_PAGE_SIZE",
    "pagination_params",
]
