"""内存事件总线实现（测试用）。

所有发布的事件直接同步调用订阅者处理器。
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog

from libs.eventbus.base import EventBus, EventHandler, EventMessage

logger = structlog.get_logger(__name__)


class InMemoryEventBus(EventBus):
    """内存事件总线：同步发布、通配订阅。"""

    def __init__(self) -> None:
        self._subscriptions: list[tuple[str, str, EventHandler]] = []
        self._started = False

    async def publish(self, topic: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        """发布事件：同步匹配所有订阅者并调用处理器。"""
        msg = EventMessage(topic=topic, payload=payload, headers=headers or {})
        logger.debug("event.publish.start", topic=topic, message_id=msg.message_id)

        for pattern, consumer_id, handler in self._subscriptions:
            if self.topic_match(topic, pattern):
                try:
                    success = await handler(msg) if asyncio.iscoroutinefunction(handler) else handler(msg)
                    if not success:
                        logger.warning("event.handler.failed", topic=topic, consumer_id=consumer_id)
                except Exception:
                    logger.exception("event.handler.error", topic=topic, consumer_id=consumer_id)

        logger.debug("event.publish.done", topic=topic, message_id=msg.message_id)
        return msg.message_id

    async def subscribe(self, topic_pattern: str, handler: EventHandler, consumer_id: str = "") -> None:
        """注册订阅者。"""
        consumer_id = consumer_id or f"consumer-{len(self._subscriptions)}"
        self._subscriptions.append((topic_pattern, consumer_id, handler))
        logger.info("event.subscribe", topic_pattern=topic_pattern, consumer_id=consumer_id)

    async def start(self) -> None:
        self._started = True
        logger.info("eventbus.memory.started")

    async def stop(self) -> None:
        self._started = False
        logger.info("eventbus.memory.stopped")

    def get_subscriptions(self) -> list[tuple[str, str]]:
        """获取当前订阅列表（测试辅助）。"""
        return [(p, c) for p, c, _ in self._subscriptions]
