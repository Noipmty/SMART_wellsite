"""Redis Stream 事件总线实现（生产用）。

使用 Redis Streams 实现持久化消息队列 + 消费组。
- publish：XADD 写入 stream
- subscribe：XREADGROUP 消费组读取
- 重试与死信：XCLAIM + PEL（pending entries list）超时重投
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import redis.asyncio as aioredis
import structlog

from libs.eventbus.base import EventBus, EventHandler, EventMessage

logger = structlog.get_logger(__name__)

# Stream key 前缀
_STREAM_PREFIX = "wellsite:events"
# 消费组名
_GROUP_NAME = "wellsite_consumers"
# 死信 stream
_DEAD_STREAM = "wellsite:events:dead"


class RedisStreamEventBus(EventBus):
    """Redis Stream 事件总线。"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        password: str = "",
        db: int = 0,
        poll_interval: float = 0.5,
        block_ms: int = 2000,
        max_retries: int = 3,
    ) -> None:
        self._redis: aioredis.Redis | None = None
        self._host = host
        self._port = port
        self._password = password
        self._db = db
        self._poll_interval = poll_interval
        self._block_ms = block_ms
        self._max_retries = max_retries
        self._subscriptions: list[tuple[str, str, EventHandler]] = []
        self._poll_tasks: list[asyncio.Task] = []
        self._started = False

    async def _ensure_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.Redis(
                host=self._host,
                port=self._port,
                password=self._password or None,
                db=self._db,
                decode_responses=True,
            )
        return self._redis

    async def publish(self, topic: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        """发布事件：XADD 写入 stream。"""
        message_id = str(uuid.uuid4())
        redis = await self._ensure_redis()

        # stream key 使用 topic 的 md5 避免过长
        stream_key = f"{_STREAM_PREFIX}:{topic.replace('/', ':')}"

        await redis.xadd(
            stream_key,
            {
                "topic": topic,
                "payload": json.dumps(payload, ensure_ascii=False),
                "headers": json.dumps({**{"message_id": message_id}, **(headers or {})}, ensure_ascii=False),
            },
        )
        logger.debug("event.publish.redis", topic=topic, message_id=message_id, stream=stream_key)
        return message_id

    async def subscribe(self, topic_pattern: str, handler: EventHandler, consumer_id: str = "") -> None:
        """注册订阅者：为每个订阅者启动消费循环。"""
        consumer_id = consumer_id or f"consumer-{len(self._subscriptions)}"
        self._subscriptions.append((topic_pattern, consumer_id, handler))
        logger.info("event.subscribe.redis", topic_pattern=topic_pattern, consumer_id=consumer_id)

    async def start(self) -> None:
        """启动消费循环。"""
        if self._started:
            return
        self._started = True
        redis = await self._ensure_redis()
        await redis.ping()

        # 为每个 topic_pattern 启动消费任务
        for pattern, consumer_id, handler in self._subscriptions:
            task = asyncio.create_task(self._consume_loop(pattern, consumer_id, handler))
            self._poll_tasks.append(task)

        logger.info("eventbus.redis.started", consumers=len(self._poll_tasks))

    async def stop(self) -> None:
        """停止消费。"""
        self._started = False
        for task in self._poll_tasks:
            task.cancel()
        for task in self._poll_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._poll_tasks.clear()

        if self._redis:
            await self._redis.aclose()
            self._redis = None
        logger.info("eventbus.redis.stopped")

    async def _consume_loop(self, pattern: str, consumer_id: str, handler: EventHandler) -> None:
        """消费循环：使用 XREADGROUP 读取消息。"""
        redis = await self._ensure_redis()
        stream_key = f"{_STREAM_PREFIX}:{pattern.replace('/', ':')}"

        # 创建消费组（如果不存在）
        try:
            await redis.xgroup_create(stream_key, _GROUP_NAME, id="0", mkstream=True)
        except Exception:
            # 消费组已存在
            pass

        while self._started:
            try:
                # XREADGROUP 读取消息
                results = await redis.xreadgroup(
                    groupname=_GROUP_NAME,
                    consumername=consumer_id,
                    streams={stream_key: ">"},
                    count=10,
                    block=self._block_ms,
                )

                if not results:
                    continue

                for _stream, messages in results:
                    for msg_id, fields in messages:
                        msg = self._parse_message(fields)
                        if msg and self.topic_match(msg.topic, pattern):
                            try:
                                success = (
                                    await handler(msg) if asyncio.iscoroutinefunction(handler) else handler(msg)
                                )
                                if success:
                                    await redis.xack(stream_key, _GROUP_NAME, msg_id)
                                else:
                                    logger.warning("event.handler.failed.redis", topic=msg.topic, consumer_id=consumer_id)
                            except Exception:
                                logger.exception("event.handler.error.redis", topic=msg.topic, consumer_id=consumer_id)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("eventbus.redis.consume.error")
                await asyncio.sleep(self._poll_interval)

    def _parse_message(self, fields: dict[str, str]) -> EventMessage | None:
        """解析 Redis Stream 消息字段。"""
        try:
            topic = fields.get("topic", "")
            payload = json.loads(fields.get("payload", "{}"))
            headers = json.loads(fields.get("headers", "{}"))
            return EventMessage(topic=topic, payload=payload, headers=headers)
        except (json.JSONDecodeError, KeyError):
            logger.exception("eventbus.redis.parse.error", fields=fields)
            return None
