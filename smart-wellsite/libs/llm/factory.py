"""LLM 客户端工厂：根据配置创建对应实现。"""

from __future__ import annotations

import structlog

from configs import get_settings
from libs.llm.base import LLMClient
from libs.llm.mock import MockLLMClient

logger = structlog.get_logger(__name__)


def create_llm_client() -> LLMClient:
    """根据配置创建 LLM 客户端实例。"""
    settings = get_settings()

    logger.info("llm.factory", provider=settings.llm_provider)

    if settings.llm_provider == "mock":
        return MockLLMClient(
            timeout=settings.llm_timeout,
            max_retries=settings.llm_max_retries,
            token_budget=settings.llm_token_budget,
        )
    elif settings.llm_provider == "doubao":
        # 预留豆包实现（阶段二/三）
        raise NotImplementedError("豆包 LLM 客户端待实现")
    elif settings.llm_provider == "deepseek":
        # 预留 DeepSeek 实现（阶段二/三）
        raise NotImplementedError("DeepSeek LLM 客户端待实现")
    else:
        raise ValueError(f"未知的 LLM provider: {settings.llm_provider}")
