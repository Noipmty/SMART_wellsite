"""事件总线抽象接口与数据结构。

Topic 规范: wellsite/{site_id}/{domain}/{event_type}
示例: wellsite/WS001/sensor/DEV001/load_anomaly
通配: wellsite/WS001/sensor/* / wellsite/+/sensor/#
"""

from __future__ import annotations

import abc
import fnmatch
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class EventMessage(BaseModel):
    """事件消息体。"""

    model_config = ConfigDict()

    topic: str = Field(description="事件主题，如 wellsite/WS001/sensor/DEV001/load_anomaly")
    payload: dict[str, Any] = Field(description="事件载荷 JSON")
    headers: dict[str, str] = Field(default_factory=dict, description="事件头（trace_id / agent_id 等）")
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="消息唯一 ID")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EventEnvelope(BaseModel):
    """事件信封（含投递元数据）。"""

    message: EventMessage
    consumer_id: str = ""
    delivered_at: datetime | None = None
    retry_count: int = 0


# 处理器类型：接收事件消息，返回是否成功
EventHandler = Callable[[EventMessage], bool]


class EventBus(abc.ABC):
    """事件总线抽象接口。

    实现：
    - InMemoryEventBus：内存实现（测试用）
    - MysqlEventBus：MySQL 模拟实现（本地开发，表轮询模拟发布订阅）
    - RedisStreamEventBus：Redis Stream 实现（生产）
    """

    @abc.abstractmethod
    async def publish(self, topic: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        """发布事件到指定 topic，返回 message_id。"""
        ...

    @abc.abstractmethod
    async def subscribe(self, topic_pattern: str, handler: EventHandler, consumer_id: str = "") -> None:
        """订阅匹配 topic_pattern 的事件。支持通配符 * 和 #。

        - * 匹配单层 topic
        - # 匹配多层 topic（类似 MQTT 的 #）
        """
        ...

    @abc.abstractmethod
    async def start(self) -> None:
        """启动事件总线（如启动轮询线程或 Redis 消费组）。"""
        ...

    @abc.abstractmethod
    async def stop(self) -> None:
        """停止事件总线。"""
        ...

    @staticmethod
    def topic_match(topic: str, pattern: str) -> bool:
        """检查 topic 是否匹配 pattern。

        支持三种通配：
        - * 或 + 匹配单层（wellsite/WS001/* 匹配 wellsite/WS001/sensor 但不匹配 wellsite/WS001/sensor/DEV001）
        - # 匹配多层（wellsite/WS001/# 匹配 wellsite/WS001/sensor/DEV001/load_anomaly）
        - 混合使用：wellsite/*/sensor/# 匹配 wellsite/WS001/sensor/DEV001/load
        """
        # 支持 + 作为 * 的别名（MQTT 兼容）
        pattern = pattern.replace("+", "*")

        # 处理 # 通配
        if "#" in pattern:
            # 找到 # 的位置，前面的部分需要精确匹配（含 * 层）
            hash_idx = pattern.index("#")
            prefix_pattern = pattern[:hash_idx].rstrip("/")  # 去掉 # 前的 /
            # 如果 # 是整个 pattern 的结尾
            if hash_idx == len(pattern) - 1:
                topic_parts = topic.split("/")
                prefix_parts = prefix_pattern.split("/") if prefix_pattern else []
                # 前缀层数匹配，且逐层通配
                if len(topic_parts) < len(prefix_parts):
                    return False
                for i, pp in enumerate(prefix_parts):
                    if pp == "*":
                        continue
                    if pp != topic_parts[i]:
                        return False
                return True
            # # 不在末尾，不支持
            return False

        # 无 # 通配：逐层比较，* 匹配单层
        pattern_parts = pattern.split("/")
        topic_parts = topic.split("/")
        if len(pattern_parts) != len(topic_parts):
            return False
        for pp, tp in zip(pattern_parts, topic_parts):
            if pp == "*":
                continue
            if pp != tp:
                return False
        return True
