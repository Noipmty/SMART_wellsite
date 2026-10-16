"""LLM 统一客户端模块：chat + 结构化 JSON 输出。

当前实现 MockLLMClient，预留豆包 / DeepSeek 接口。
"""

from libs.llm.base import LLMClient, LLMResponse, LLMMessage
from libs.llm.mock import MockLLMClient
from libs.llm.factory import create_llm_client

__all__ = [
    "LLMClient",
    "LLMResponse",
    "LLMMessage",
    "MockLLMClient",
    "create_llm_client",
]
