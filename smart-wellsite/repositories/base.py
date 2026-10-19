"""仓储基类：统一异步内存存储与并发保护。

当前后端使用 mock 数据源、不启数据库容器，故以内存仓储落地；
真实部署时新增 PostgreSQL/TDengine 实现并替换绑定即可，服务层与路由层零改动。
"""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class BaseRepository(abc.ABC, Generic[T]):
    """仓储抽象基类。"""

    @abc.abstractmethod
    async def count(self) -> int:
        raise NotImplementedError


class InMemoryRepository(BaseRepository[T]):
    """线程/协程安全的内存仓储基类（单进程、单事件循环）。"""

    def __init__(self) -> None:
        self._items: dict[str, T] = {}
        self._lock = asyncio.Lock()

    async def count(self) -> int:
        async with self._lock:
            return len(self._items)

    async def get(self, key: str) -> T | None:
        async with self._lock:
            return self._items.get(key)

    async def list(self, predicate: Callable[[T], bool] | None = None) -> list[T]:
        async with self._lock:
            items = list(self._items.values())
        if predicate is None:
            return items
        return [item for item in items if predicate(item)]

    async def add(self, key: str, item: T) -> T:
        async with self._lock:
            self._items[key] = item
        return item

    async def update(self, key: str, patch: Callable[[T], None]) -> T | None:
        """在锁内对已有对象做就地更新。"""
        async with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            patch(item)
            return item

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key not in self._items:
                return False
            del self._items[key]
            return True

    async def clear(self) -> None:
        async with self._lock:
            self._items.clear()
