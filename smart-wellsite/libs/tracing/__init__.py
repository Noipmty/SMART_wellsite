"""LangSmith 追踪与 structlog 日志初始化。"""

from __future__ import annotations

import os
import sys

import structlog
from configs import get_settings


def setup_logging() -> None:
    """初始化 structlog 结构化日志。"""
    settings = get_settings()

    log_level = settings.log_level.upper()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, f"make_filtering_bound_logger", None) and
            __import__("logging").getLevelName(log_level)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )


def setup_tracing() -> None:
    """初始化 LangSmith 追踪。"""
    settings = get_settings()

    if settings.langsmith_tracing and settings.langsmith_api_key:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
        os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

        logger = structlog.get_logger(__name__)
        logger.info("tracing.langsmith.enabled", project=settings.langsmith_project)
    else:
        # 开发环境不启用
        os.environ["LANGCHAIN_TRACING_V2"] = "false"

        logger = structlog.get_logger(__name__)
        logger.info("tracing.langsmith.disabled")


def setup_observability() -> None:
    """一键初始化日志 + 追踪。"""
    setup_logging()
    setup_tracing()
