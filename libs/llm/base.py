"""LLM 客户端抽象接口与数据结构。"""

from __future__ import annotations

import abc
from datetime import datetime, timezone
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    """对话消息。"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class LLMResponse(BaseModel):
    """LLM 响应。"""

    content: str = Field(description="生成的文本内容")
    role: str = "assistant"
    model: str = ""
    usage: dict[str, int] = Field(default_factory=dict, description="token 用量")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw: dict[str, Any] | None = None


class LLMClient(abc.ABC):
    """LLM 客户端抽象接口。

    统一封装：chat + 结构化 JSON mode 输出。
    预留豆包 / DeepSeek 实现。
    """

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """对话接口，返回文本响应。"""
        ...

    @abc.abstractmethod
    async def chat_with_json(
        self,
        messages: list[LLMMessage],
        response_model: type[T],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> T:
        """结构化输出：通过 JSON mode 返回指定 pydantic 模型。

        Args:
            messages: 对话消息列表
            response_model: 期望的 pydantic 模型类型
            temperature: 温度，默认 0.3（结构化输出用低温度）
            max_tokens: 最大 token 数
        """
        ...

    async def stream_chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        """流式输出。默认实现降级为非流式。

        Yields: str - 逐段文本
        """
        resp = await self.chat(messages, temperature, max_tokens, **kwargs)
        yield resp.content
