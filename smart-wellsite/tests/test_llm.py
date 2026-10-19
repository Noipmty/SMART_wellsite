"""MockLLMClient 测试：chat + 结构化 JSON 输出。"""

import pytest
from pydantic import BaseModel, Field

from libs.llm.mock import MockLLMClient
from libs.llm.base import LLMMessage


@pytest.mark.asyncio
async def test_chat_basic(mock_llm):
    """chat 基本测试。"""
    messages = [
        LLMMessage(role="system", content="你是智慧井场值班助手。"),
        LLMMessage(role="user", content="3号井有什么故障？"),
    ]
    resp = await mock_llm.chat(messages)
    assert resp.content
    assert "供液不足" in resp.content or "故障" in resp.content
    assert resp.role == "assistant"
    assert resp.model == "mock-llm-v1"


@pytest.mark.asyncio
async def test_chat_default(mock_llm):
    """默认响应测试。"""
    messages = [LLMMessage(role="user", content="你好")]
    resp = await mock_llm.chat(messages)
    assert "值班助手" in resp.content


@pytest.mark.asyncio
async def test_chat_with_json(mock_llm):
    """结构化 JSON 输出测试。"""

    class FaultDiagnosis(BaseModel):
        well_id: str
        device_id: str
        fault_type: str
        confidence: float
        evidence: list[dict]
        recommendation: str

    messages = [LLMMessage(role="user", content="诊断 3 号井故障")]
    result = await mock_llm.chat_with_json(messages, FaultDiagnosis)

    assert isinstance(result, FaultDiagnosis)
    assert result.well_id == "WELL-003"
    assert result.fault_type == "insufficient_supply"
    assert 0 <= result.confidence <= 1
    assert len(result.evidence) > 0
    assert result.recommendation


@pytest.mark.asyncio
async def test_stream_chat(mock_llm):
    """流式输出测试。"""
    messages = [LLMMessage(role="user", content="帮我查看告警")]
    chunks = []
    async for chunk in mock_llm.stream_chat(messages):
        chunks.append(chunk)

    assert len(chunks) > 1
    full_text = "".join(chunks)
    assert "告警" in full_text


@pytest.mark.asyncio
async def test_usage_reported(mock_llm):
    """token 用量应被记录。"""
    messages = [LLMMessage(role="user", content="什么是供液不足？")]
    resp = await mock_llm.chat(messages)
    assert "total_tokens" in resp.usage
    assert resp.usage["total_tokens"] > 0
