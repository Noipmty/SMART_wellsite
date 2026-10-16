"""知识库仓储：文档与分块的内存实现（真实部署换 PostgreSQL + 向量库绑定）。"""

from __future__ import annotations

from libs.schemas.kb import KBChunk, KBDocument, IndexStatus
from repositories.base import InMemoryRepository


class KBDocumentRepository(InMemoryRepository[KBDocument]):
    """doc_id → KBDocument；支持状态/类型过滤，按创建时间倒序。"""

    async def save(self, doc: KBDocument) -> KBDocument:
        return await self.add(doc.doc_id, doc)

    async def get_by_id(self, doc_id: str) -> KBDocument | None:
        return await self.get(doc_id)

    async def query(
        self,
        status: IndexStatus | None = None,
        doc_type: str | None = None,
    ) -> list[KBDocument]:
        def predicate(d: KBDocument) -> bool:
            if status and d.status is not status:
                return False
            if doc_type and d.doc_type != doc_type:
                return False
            return True

        items = await self.list(predicate)
        items.sort(key=lambda d: d.created_at, reverse=True)
        return items


class KBChunkRepository(InMemoryRepository[KBChunk]):
    """chunk_id → KBChunk；支持按文档批量查询与删除。"""

    async def save_all(self, chunks: list[KBChunk]) -> None:
        for chunk in chunks:
            await self.add(chunk.chunk_id, chunk)

    async def list_by_doc(self, doc_id: str) -> list[KBChunk]:
        items = await self.list(lambda c: c.doc_id == doc_id)
        items.sort(key=lambda c: c.seq)
        return items

    async def delete_by_doc(self, doc_id: str) -> int:
        chunks = await self.list_by_doc(doc_id)
        for chunk in chunks:
            await self.delete(chunk.chunk_id)
        return len(chunks)

    async def list_ready(self, ready_doc_ids: set[str]) -> list[KBChunk]:
        return await self.list(lambda c: c.doc_id in ready_doc_ids)
