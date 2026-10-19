"""事件总线工厂：根据配置创建对应实现。"""

from __future__ import annotations

import structlog

from configs import get_settings
from libs.eventbus.base import EventBus
from libs.eventbus.memory import InMemoryEventBus
from libs.eventbus.mysql_impl import MysqlEventBus
from libs.eventbus.redis_impl import RedisStreamEventBus

logger = structlog.get_logger(__name__)


def create_eventbus(backend: str | None = None) -> EventBus:
    """根据配置创建事件总线实例。

    Args:
        backend: 可选覆盖配置的 backend，用于测试
    """
    settings = get_settings()
    backend = backend or settings.eventbus_backend

    logger.info("eventbus.factory", backend=backend)

    if backend == "memory":
        return InMemoryEventBus()
    elif backend == "mysql":
        return MysqlEventBus(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
        )
    elif backend == "redis_stream":
        return RedisStreamEventBus(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
        )
    else:
        raise ValueError(f"未知的事件总线后端: {backend}")
