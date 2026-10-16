"""知识库仓储：文档与分块的内存实现（真实部署换 PostgreSQL + 向量库绑定）。"""

from __future__ import annotations

from libs.schemas.kb import (
    CandidateStatus,
    KBCandidate,
    KBChunk,
    KBDocument,
    IndexStatus,
)
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


class KBCandidateRepository(InMemoryRepository[KBCandidate]):
    """candidate_id → KBCandidate；按状态过滤，按创建时间倒序。"""

    async def save(self, candidate: KBCandidate) -> KBCandidate:
        return await self.add(candidate.candidate_id, candidate)

    async def get_by_id(self, candidate_id: str) -> KBCandidate | None:
        return await self.get(candidate_id)

    async def find_by_source(self, source_type: str,
                             source_id: str) -> KBCandidate | None:
        """按幂等键查找已沉淀候选。"""
        items = await self.list(
            lambda c: c.source_type == source_type and c.source_id == source_id
        )
        return items[0] if items else None

    async def query(self,
                    status: CandidateStatus | None = None) -> list[KBCandidate]:
        items = await self.list(
            (lambda c: c.status is status) if status else None
        )
        items.sort(key=lambda c: c.created_at, reverse=True)
        return items
