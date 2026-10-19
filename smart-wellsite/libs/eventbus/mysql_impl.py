"""MySQL 模拟事件总线实现（本地开发用）。

通过 event_messages 表 + 轮询机制模拟发布订阅。
- publish：INSERT 一条 pending 消息
- subscribe：注册 consumer_id + topic_pattern 到 event_subscriptions 表
- 轮询线程：SELECT pending 消息，匹配订阅者后调用处理器
- 重试与死信：超过 max_retries 的消息进入 event_dead_letters 表
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any

import mysql.connector
import structlog

from libs.eventbus.base import EventBus, EventHandler, EventMessage

logger = structlog.get_logger(__name__)

_CREATE_MSG_SQL = """
INSERT INTO event_messages (topic, payload, headers, status, max_retries)
VALUES (%s, %s, %s, 'pending', %s)
"""

_POLL_SQL = """
SELECT id, topic, payload, headers, retry_count, max_retries
FROM event_messages
WHERE status = 'pending'
ORDER BY created_at ASC
LIMIT %s
"""

_UPDATE_DELIVERED_SQL = """
UPDATE event_messages
SET status = 'delivered', delivered_at = %s, consumer_id = %s, retry_count = retry_count + 1
WHERE id = %s AND status = 'pending'
"""

_MOVE_DEAD_SQL = """
INSERT INTO event_dead_letters (original_id, topic, payload, headers, error, retry_count)
VALUES (%s, %s, %s, %s, %s, %s)
"""

_DELETE_DELIVERED_SQL = "DELETE FROM event_messages WHERE id = %s"


class MysqlEventBus(EventBus):
    """MySQL 模拟事件总线：表 + 轮询。"""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "wellsite",
        password: str = "wellsite_dev_2026",
        database: str = "wellsite_bus",
        poll_interval: float = 0.5,
        batch_size: int = 50,
        default_max_retries: int = 3,
    ) -> None:
        self._conn_params = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
            "autocommit": True,
        }
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._default_max_retries = default_max_retries
        self._subscriptions: list[tuple[str, str, EventHandler]] = []
        self._poll_task: asyncio.Task | None = None
        self._started = False
        self._pool: mysql.connector.pooling.MySQLConnectionPool | None = None

    def _get_conn(self):
        """获取数据库连接（从连接池）。"""
        if self._pool is None:
            self._pool = mysql.connector.pooling.MySQLConnectionPool(
                pool_name="eventbus_pool",
                pool_size=5,
                **self._conn_params,
            )
        return self._pool.get_connection()

    async def publish(self, topic: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> str:
        """发布事件：INSERT 到 event_messages 表。"""
        message_id = str(uuid.uuid4())
        full_headers = {"message_id": message_id, **(headers or {})}

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            self._publish_sync,
            topic,
            payload,
            full_headers,
        )
        logger.debug("event.publish.mysql", topic=topic, message_id=message_id)
        return message_id

    def _publish_sync(self, topic: str, payload: dict[str, Any], headers: dict[str, str]) -> None:
        """同步写入消息表。"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                _CREATE_MSG_SQL,
                (topic, json.dumps(payload, ensure_ascii=False), json.dumps(headers), self._default_max_retries),
            )
            conn.commit()
            cursor.close()
        finally:
            conn.close()

    async def subscribe(self, topic_pattern: str, handler: EventHandler, consumer_id: str = "") -> None:
        """注册订阅者：记录到内存列表。"""
        consumer_id = consumer_id or f"consumer-{len(self._subscriptions)}"
        self._subscriptions.append((topic_pattern, consumer_id, handler))
        logger.info("event.subscribe.mysql", topic_pattern=topic_pattern, consumer_id=consumer_id)

    async def start(self) -> None:
        """启动轮询线程。"""
        if self._started:
            return
        self._started = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("eventbus.mysql.started", poll_interval=self._poll_interval)

    async def stop(self) -> None:
        """停止轮询。"""
        self._started = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("eventbus.mysql.stopped")

    async def _poll_loop(self) -> None:
        """轮询 event_messages 表，分发 pending 消息。"""
        while self._started:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("eventbus.mysql.poll.error")
            await asyncio.sleep(self._poll_interval)

    async def _poll_once(self) -> None:
        """单次轮询：拉取 pending 消息并分发。"""
        loop = asyncio.get_event_loop()
        messages = await loop.run_in_executor(None, self._fetch_pending)
        if not messages:
            return

        for msg_row in messages:
            await self._dispatch(msg_row)

    def _fetch_pending(self) -> list[dict]:
        """拉取 pending 消息。"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(_POLL_SQL, (self._batch_size,))
            rows = cursor.fetchall()
            cursor.close()
            return rows
        finally:
            conn.close()

    async def _dispatch(self, msg_row: dict) -> None:
        """分发单条消息到匹配的订阅者。"""
        topic = msg_row["topic"]
        msg_id = msg_row["id"]
        payload = msg_row["payload"]
        headers = msg_row["headers"] or {}
        retry_count = msg_row["retry_count"]
        max_retries = msg_row["max_retries"]

        # 解析 JSON
        if isinstance(payload, str):
            payload = json.loads(payload)
        if isinstance(headers, str):
            headers = json.loads(headers)

        msg = EventMessage(
            topic=topic,
            payload=payload,
            headers=headers,
            message_id=headers.get("message_id", str(msg_id)),
        )

        matched = False
        any_success = False

        for pattern, consumer_id, handler in self._subscriptions:
            if self.topic_match(topic, pattern):
                matched = True
                try:
                    success = await handler(msg) if asyncio.iscoroutinefunction(handler) else handler(msg)
                    if success:
                        any_success = True
                except Exception:
                    logger.exception("event.handler.error", topic=topic, consumer_id=consumer_id, msg_id=msg_id)

        if not matched:
            # 无匹配订阅者，直接标记已投递
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._mark_delivered, msg_id, "no-subscriber")
        elif any_success:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._mark_delivered, msg_id, "dispatched")
        elif retry_count + 1 >= max_retries:
            # 超过重试次数 -> 死信
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._move_to_dead, msg_row)
            logger.warning("event.dead_letter", topic=topic, msg_id=msg_id, retries=retry_count)

    def _mark_delivered(self, msg_id: int, consumer_id: str) -> None:
        """标记消息已投递。"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(_UPDATE_DELIVERED_SQL, (datetime.now(timezone.utc), consumer_id, msg_id))
            conn.commit()
            cursor.close()
        finally:
            conn.close()

    def _move_to_dead(self, msg_row: dict) -> None:
        """将消息移入死信表。"""
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                _MOVE_DEAD_SQL,
                (
                    msg_row["id"],
                    msg_row["topic"],
                    msg_row["payload"],
                    msg_row["headers"],
                    "max_retries_exceeded",
                    msg_row["retry_count"],
                ),
            )
            cursor.execute(_DELETE_DELIVERED_SQL, (msg_row["id"],))
            conn.commit()
            cursor.close()
        finally:
            conn.close()
