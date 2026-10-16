"""链路追踪仓储：保存并检索 TraceRecord。"""

from __future__ import annotations

from datetime import datetime

from libs.schemas.trace import TraceRecord
from repositories.base import InMemoryRepository


class TraceRepository(InMemoryRepository[TraceRecord]):
    """trace_id → TraceRecord；按时间倒序列出。"""

    async def save(self, record: TraceRecord) -> TraceRecord:
        return await self.add(record.trace_id, record)

    async def query(
        self,
        session_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[TraceRecord]:
        """按会话 / 时间窗口过滤，按创建时间倒序返回。"""

        def predicate(r: TraceRecord) -> bool:
            if session_id and r.session_id != session_id:
                return False
            if start and r.created_at < start:
                return False
            if end and r.created_at > end:
                return False
            return True

        items = await self.list(predicate)
        items.sort(key=lambda r: r.created_at, reverse=True)
        return items
