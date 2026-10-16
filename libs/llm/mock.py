"""MockLLMClient：返回预设结构化输出。

用于本地开发和测试，不调用实际 LLM API。
支持：
- chat：返回预设对话内容
- chat_with_json：返回符合 response_model 的预设 JSON
- stream_chat：逐字输出预设内容
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from libs.llm.base import LLMClient, LLMMessage, LLMResponse

logger = structlog.get_logger(__name__)

T = TypeVar("T")

# ====== Mock 响应模板 ======
_MOCK_CHAT_RESPONSES: dict[str, str] = {
    "诊断": "根据传感器数据分析，3号井抽油机存在供液不足故障，置信度 85%。建议检查泵效和液面深度，必要时调整冲次。",
    "告警": "当前有2条未处理告警：1条预警级（供液不足），1条提醒级（电流波动）。建议优先处理供液不足预警。",
    "知识": "供液不足是指抽油泵在吸入过程中液体不能充满泵筒，常见原因包括：地层供液能力下降、井底压力低、泵深不合理等。",
    "控制": "已收到控制指令请求。根据安全策略，该操作需要人工确认。请等待值班员审批后执行。",
    "default": "您好，我是智慧井场值班助手。我可以帮您查询井场数据、诊断设备故障、查看告警状态、回答知识问题。请问需要什么帮助？",
}

_MOCK_JSON_TEMPLATES: dict[str, dict[str, Any]] = {
    "FaultDiagnosis": {
        "well_id": "WELL-003",
        "device_id": "DEV-003",
        "fault_type": "insufficient_supply",
        "confidence": 0.85,
        "evidence": [
            {"indicator": "pump_efficiency", "value": 0.42, "threshold": 0.65, "deviation": "-35.4%"},
            {"indicator": "load_range", "value": 28.5, "unit": "kN", "threshold": 35.0},
        ],
        "recommendation": "建议检查泵效和液面深度，适当调低冲次以匹配供液能力。",
    },
    "AlertLevel": {
        "level": "warning",
        "title": "供液不足预警",
        "description": "3号井抽油机泵效持续低于阈值",
        "action": "notify",
    },
    "ChatIntent": {
        "intent": "query_data",
        "entities": {"well_id": "WELL-003", "param": "load"},
        "confidence": 0.92,
    },
}


def _agent_json(model_name: str, user_text: str) -> dict[str, Any] | None:
    """按 Agent 输出模型名生成贴近输入的结构化 mock（模拟 LLM 推理）。

    让 mock 结果随输入证据变化，避免"任何问题都返回同一结论"。
    """
    if model_name == "DiagnosisOutput":
        if any(k in user_text for k in ("检修", "停电", "限产")):
            return {
                "diagnosis": "人工事件（检修/停电/限产）导致的停产，非设备故障",
                "confidence": 0.9, "evidence": [],
                "suggestion": "核对事件日历，无需设备处置",
                "needs_review": False, "known_event": "命中事件日历",
            }
        if "沉没度" in user_text and ("下行" in user_text or "下降" in user_text):
            return {
                "diagnosis": "供液不足", "confidence": 0.87, "evidence": [],
                "suggestion": "建议调低冲次观察 4 小时（需人工确认后执行）",
                "needs_review": True, "known_event": None,
            }
        return {
            "diagnosis": "无法确定", "confidence": 0.55, "evidence": [],
            "suggestion": "需补充更长时间窗口 / 振动频谱 / 现场照片",
            "needs_review": True, "known_event": None,
        }
    if model_name == "ProductionOutput":
        if "下行" in user_text or "下降" in user_text:
            return {
                "conclusion": "产量下降，多参数交叉验证指向供液不足",
                "confidence": 0.82, "evidence": [],
                "parameter_advice": [{
                    "param": "冲次", "from": 6, "to": 4,
                    "reason": "匹配地层供液能力，避免泵抽空",
                    "confirm_required": True, "observe_hours": 4.0,
                }],
            }
        return {"conclusion": "各项参数处于正常波动范围", "confidence": 0.7,
                "evidence": [], "parameter_advice": []}
    if model_name == "RiskOutput":
        if "H2S" in user_text:
            return {"risk_level": "预警", "description": "井口 H2S 浓度超过预警值",
                    "affected_area": "井口周边 50 米",
                    "action_suggestion": "安排人员佩戴检测仪上风向确认，暂停周边动火作业",
                    "must_human_confirm": True}
        return {"risk_level": "提醒", "description": "轻微隐患，可安排巡检确认",
                "affected_area": "现场", "action_suggestion": "安排巡检确认",
                "must_human_confirm": True}
    if model_name == "ReportKnowledgeOutput":
        return {"answer": "已依据检索到的知识库条目作答，详见来源引用。",
                "source_refs": [], "report": None}
    if model_name == "StructuredIntent":
        return {"intent": "production_analysis", "entities": {},
                "confidence": 0.8, "need_clarify": False, "clarify_options": []}
    if model_name == "RoutingOutput":
        return {"subtasks": [], "needs_review": False}
    return None


class MockLLMClient(LLMClient):
    """Mock LLM 客户端：返回预设响应。"""

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        token_budget: int = 4096,
        delay: float = 0.05,
    ) -> None:
        self._timeout = timeout
        self._max_retries = max_retries
        self._token_budget = token_budget
        self._delay = delay  # 模拟延迟

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=1.0),
        retry=retry_if_exception_type(TimeoutError),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """返回预设对话内容。根据用户消息关键词匹配模板。"""
        await asyncio.sleep(self._delay)  # 模拟网络延迟

        user_msg = ""
        for m in messages:
            if m.role == "user":
                user_msg = m.content
                break

        content = self._match_response(user_msg)

        logger.debug("llm.mock.chat", content_len=len(content), user_msg=user_msg[:100])

        return LLMResponse(
            content=content,
            role="assistant",
            model="mock-llm-v1",
            usage={
                "prompt_tokens": len(user_msg) // 4,
                "completion_tokens": len(content) // 4,
                "total_tokens": (len(user_msg) + len(content)) // 4,
            },
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=1.0),
        retry=retry_if_exception_type(TimeoutError),
        reraise=True,
    )
    async def chat_with_json(
        self,
        messages: list[LLMMessage],
        response_model: type[T],
        temperature: float = 0.3,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> T:
        """返回符合 response_model 的预设 JSON。"""
        await asyncio.sleep(self._delay)

        user_msg = ""
        for m in messages:
            if m.role == "user":
                user_msg = m.content

        model_name = response_model.__name__
        template = _MOCK_JSON_TEMPLATES.get(model_name)
        if template is None:
            template = _agent_json(model_name, user_msg)

        if template is None:
            # 如果没有预设模板，尝试从 model_fields 生成默认值
            logger.warning("llm.mock.json.no_template", model=model_name)
            template = self._generate_default(response_model)

        # 验证并返回
        result = response_model.model_validate(template)
        logger.debug("llm.mock.json", model=model_name)
        return result

    async def stream_chat(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ):
        """逐字输出预设内容。"""
        user_msg = ""
        for m in messages:
            if m.role == "user":
                user_msg = m.content
                break

        content = self._match_response(user_msg)
        for char in content:
            yield char
            await asyncio.sleep(0.01)

    def _match_response(self, user_msg: str) -> str:
        """根据用户消息关键词匹配预设响应。"""
        if "诊断" in user_msg or "故障" in user_msg or "问题" in user_msg:
            return _MOCK_CHAT_RESPONSES["诊断"]
        elif "告警" in user_msg or "报警" in user_msg:
            return _MOCK_CHAT_RESPONSES["告警"]
        elif "知识" in user_msg or "什么是" in user_msg or "原理" in user_msg:
            return _MOCK_CHAT_RESPONSES["知识"]
        elif "停" in user_msg or "启" in user_msg or "控制" in user_msg or "调参" in user_msg:
            return _MOCK_CHAT_RESPONSES["控制"]
        else:
            return _MOCK_CHAT_RESPONSES["default"]

    def _generate_default(self, model: type[T]) -> dict[str, Any]:
        """根据 model_fields 生成默认值。"""
        result = {}
        for field_name, field_info in model.model_fields.items():
            ann = field_info.annotation
            if ann is str or ann == "str":
                result[field_name] = f"mock_{field_name}"
            elif ann is int or ann == "int":
                result[field_name] = 0
            elif ann is float or ann == "float":
                result[field_name] = 0.0
            elif ann is bool or ann == "bool":
                result[field_name] = False
            elif hasattr(ann, "__origin__") and ann.__origin__ is list:
                result[field_name] = []
            elif hasattr(ann, "__origin__") and ann.__origin__ is dict:
                result[field_name] = {}
            else:
                result[field_name] = None
        return result
