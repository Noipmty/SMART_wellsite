"""知识库服务：文档上传、分块索引状态机、检索、删除级联、种子初始化。

索引状态机：pending → indexing → ready / failed
- create_document 落库 PENDING 后，默认以后台任务异步索引（生产语义）；
  测试可传 background=False 后手动 await index_document，保证确定性。
- 分块为纯 CPU 操作且 mock 文本短，后台任务一拍事件循环即可完成。
检索沿用 sim 的关键词重合度评分（tag×2 / title×3 / 字符重合封顶 20），
仅命中 READY 文档的分块；返回 dict 兼容报表知识 Agent 的现有消费方式。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import structlog

from libs.api.errors import ConflictError, NotFoundError
from libs.schemas.kb import (
    CandidateStatus,
    IndexStatus,
    KBCandidate,
    KBChunk,
    KBDocument,
)
from repositories.kb_repo import (
    KBCandidateRepository,
    KBChunkRepository,
    KBDocumentRepository,
)

logger = structlog.get_logger(__name__)

MAX_CHUNK_CHARS = 300
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？；\n])")

# 领域关键词表：用于分块 tag 自动抽取（补充上传时人工 tags）
DOMAIN_KEYWORDS: tuple[str, ...] = (
    "H2S", "硫化氢", "供液不足", "泵效", "沉没度", "冲次", "抽油机",
    "节流", "水合物", "结蜡", "采气", "钻压", "转速", "泥浆密度", "井涌",
    "安全帽", "违规闯入", "动火", "应急", "撤离", "检修", "压力", "产量",
)


def chunk_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """结构感知分块：优先按段落切，长段按句子边界切，过短相邻段合并。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    blocks: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            blocks.append(para)
            continue
        sentences = [s for s in _SENTENCE_SPLIT.split(para) if s.strip()]
        buf = ""
        for sent in sentences:
            if buf and len(buf) + len(sent) > max_chars:
                blocks.append(buf.strip())
                buf = sent
            else:
                buf += sent
        if buf.strip():
            blocks.append(buf.strip())
    # 合并过短相邻块，避免碎块
    merged: list[str] = []
    for block in blocks:
        if merged and len(merged[-1]) + len(block) <= max_chars // 2:
            merged[-1] = merged[-1] + "\n" + block
        else:
            merged.append(block)
    return merged or [text.strip()]


def extract_tags(text: str, extra: list[str] | None = None) -> list[str]:
    """从文本抽取领域关键词作为 tag，并入人工指定 tags（去重保序）。"""
    tags: list[str] = []
    for kw in DOMAIN_KEYWORDS:
        if kw in text and kw not in tags:
            tags.append(kw)
    for tag in extra or []:
        if tag and tag not in tags:
            tags.append(tag)
    return tags


class KBService:
    """知识库领域服务（每个依赖容器持有一个实例）。"""

    def __init__(self, doc_repo: KBDocumentRepository,
                 chunk_repo: KBChunkRepository,
                 candidate_repo: KBCandidateRepository | None = None) -> None:
        self._docs = doc_repo
        self._chunks = chunk_repo
        self._candidates = candidate_repo or KBCandidateRepository()
        self._tasks: set[asyncio.Task] = set()

    # ---------------- 上传与索引 ----------------

    async def create_document(
        self,
        title: str,
        doc_type: str,
        source_ref: str,
        text: str,
        tags: list[str] | None = None,
        *,
        background: bool = True,
    ) -> KBDocument:
        """上传文档：落库 PENDING 并触发索引（默认后台任务）。"""
        doc = KBDocument(
            title=title, doc_type=doc_type, source_ref=source_ref,
            text=text, tags=list(tags or []),
        )
        await self._docs.save(doc)
        logger.info("kb.doc_created", doc_id=doc.doc_id, title=title,
                    doc_type=doc_type)
        if background:
            task = asyncio.create_task(self.index_document(doc.doc_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        else:
            await self.index_document(doc.doc_id)
        return doc

    async def index_document(self, doc_id: str) -> KBDocument:
        """执行索引：pending/failed → indexing → ready（异常落 failed + error）。"""
        doc = await self._docs.get_by_id(doc_id)
        if doc is None:
            raise NotFoundError(f"知识库文档不存在：{doc_id}")

        def _to_indexing(d: KBDocument) -> None:
            d.status = IndexStatus.INDEXING
            d.error = None
            d.updated_at = datetime.now(timezone.utc)

        await self._docs.update(doc_id, _to_indexing)
        try:
            # 重建语义：先清旧分块再切新块，保证 reindex 幂等
            await self._chunks.delete_by_doc(doc_id)
            blocks = chunk_text(doc.text)
            chunks = [
                KBChunk(doc_id=doc_id, seq=i, text=block,
                        tags=extract_tags(doc.title + "\n" + block, doc.tags))
                for i, block in enumerate(blocks)
            ]
            await self._chunks.save_all(chunks)

            def _to_ready(d: KBDocument) -> None:
                d.status = IndexStatus.READY
                d.chunk_count = len(chunks)
                d.updated_at = datetime.now(timezone.utc)

            await self._docs.update(doc_id, _to_ready)
            logger.info("kb.doc_indexed", doc_id=doc_id, chunks=len(chunks))
        except Exception as exc:  # noqa: BLE001 - 索引失败需落库可重试
            logger.exception("kb.doc_index_failed", doc_id=doc_id)

            def _to_failed(d: KBDocument) -> None:
                d.status = IndexStatus.FAILED
                d.error = str(exc)[:200]
                d.updated_at = datetime.now(timezone.utc)

            await self._docs.update(doc_id, _to_failed)
            raise
        return await self._docs.get_by_id(doc_id)  # type: ignore[return-value]

    async def reindex(self, doc_id: str) -> KBDocument:
        """重建索引（failed/ready 均可），幂等。"""
        return await self.index_document(doc_id)

    async def update_document(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        text: str | None = None,
    ) -> KBDocument:
        """更新文档标题/正文；正文变更时同步重建索引（READY 终态）。"""
        doc = await self._docs.get_by_id(doc_id)
        if doc is None:
            raise NotFoundError(f"知识库文档不存在：{doc_id}")
        now = datetime.now(timezone.utc)

        def _apply(d: KBDocument) -> None:
            if title is not None:
                d.title = title
            if text is not None:
                d.text = text
            d.updated_at = now

        await self._docs.update(doc_id, _apply)
        if text is not None:
            await self.index_document(doc_id)
        logger.info("kb.doc_updated", doc_id=doc_id,
                    title_changed=title is not None, reindexed=text is not None)
        return await self._docs.get_by_id(doc_id)  # type: ignore[return-value]

    # ---------------- 检索 ----------------

    async def search(self, query: str, top_k: int = 3,
                     doc_type: str | None = None) -> list[dict]:
        """关键词重合度检索（mock RAG），仅命中 READY 文档的分块。

        返回 dict（含 id/source_ref/type/title/text/tags/score/doc_id/chunk_id），
        与 sim.knowledge 条目结构兼容，供报表知识 Agent 与检索测试面板共用。
        """
        if not query:
            return []
        ready_docs = await self._docs.query(status=IndexStatus.READY,
                                            doc_type=doc_type)
        if not ready_docs:
            return []
        doc_map = {d.doc_id: d for d in ready_docs}
        chunks = await self._chunks.list_ready(set(doc_map))

        scored: list[tuple[int, KBChunk]] = []
        # 词级命中：查询分词后任一 ≥2 字词完整出现在正文（避免单字误命中，
        # 又避免 tag/title 硬门槛挡住自进化新知识）
        tokens = [t for t in re.split(r"[^0-9A-Za-z一-鿿]+", query) if len(t) >= 2]
        for chunk in chunks:
            doc = doc_map[chunk.doc_id]
            tag_score = sum(2 for tag in chunk.tags if tag in query)
            title_score = 3 if doc.title in query else 0
            base = tag_score + title_score
            if base == 0 and not any(t in chunk.text for t in tokens):
                continue
            char_score = sum(1 for ch in set(query)
                             if ch.strip() and ch in chunk.text)
            scored.append((base * 10 + min(char_score, 20), chunk))
        scored.sort(key=lambda x: x[0], reverse=True)

        hits: list[dict] = []
        for score, chunk in scored[:top_k]:
            doc = doc_map[chunk.doc_id]
            hits.append({
                "id": doc.doc_id,
                "chunk_id": chunk.chunk_id,
                "source_ref": doc.source_ref,
                "type": doc.doc_type,
                "title": doc.title,
                "text": chunk.text,
                "tags": chunk.tags,
                "score": score,
            })
        return hits

    # ---------------- 删除 ----------------

    async def delete_document(self, doc_id: str) -> None:
        """删除文档并级联删除其分块；不存在抛 404。"""
        doc = await self._docs.get_by_id(doc_id)
        if doc is None:
            raise NotFoundError(f"知识库文档不存在：{doc_id}")
        removed = await self._chunks.delete_by_doc(doc_id)
        await self._docs.delete(doc_id)
        logger.info("kb.doc_deleted", doc_id=doc_id, chunks_removed=removed)

    # ---------------- 种子 ----------------

    async def seed_defaults(self) -> int:
        """文档库为空时灌入 sim 的 5 条规程/预案/案例（同步索引即 READY）。"""
        if await self._docs.count() > 0:
            return 0
        from sim.knowledge import KB_ENTRIES

        for entry in KB_ENTRIES:
            await self.create_document(
                title=entry["title"], doc_type=entry["type"],
                source_ref=entry["source_ref"], text=entry["text"],
                tags=list(entry["tags"]), background=False,
            )
        logger.info("kb.seeded", count=len(KB_ENTRIES))
        return len(KB_ENTRIES)

    # ---------------- 候选沉淀（自进化管道） ----------------

    async def submit_candidate(
        self,
        source_type: str,
        source_id: str,
        title: str,
        text: str,
        doc_type: str = "案例",
        source_ref: str = "",
        tags: list[str] | None = None,
    ) -> tuple[KBCandidate, bool]:
        """沉淀一条候选知识（幂等：同一来源不重复生成）。

        返回 (候选, 是否新建)；已存在时直接返回原候选，供高频钩子安全重入。
        """
        existing = await self._candidates.find_by_source(source_type, source_id)
        if existing is not None:
            return existing, False
        candidate = KBCandidate(
            source_type=source_type, source_id=source_id,
            title=title, doc_type=doc_type, source_ref=source_ref,
            text=text, tags=extract_tags(title + "\n" + text, tags),
        )
        await self._candidates.save(candidate)
        logger.info("kb.candidate_submitted", candidate_id=candidate.candidate_id,
                    source_type=source_type, source_id=source_id)
        return candidate, True

    async def approve_candidate(
        self,
        candidate_id: str,
        reviewer: str,
        overrides: dict | None = None,
    ) -> tuple[KBCandidate, KBDocument]:
        """采纳候选：可选编辑后正式入库（同步索引即 READY）。

        仅 pending 可采纳，终态重复操作抛 409。
        """
        candidate = await self._candidates.get_by_id(candidate_id)
        if candidate is None:
            raise NotFoundError(f"候选知识不存在：{candidate_id}")
        if candidate.status is not CandidateStatus.PENDING:
            raise ConflictError(
                f"候选已处于终态 {candidate.status.value}，不可重复审核",
                details={"candidate_id": candidate_id,
                         "status": candidate.status.value},
            )
        overrides = overrides or {}
        doc = await self.create_document(
            title=overrides.get("title", candidate.title),
            doc_type=overrides.get("doc_type", candidate.doc_type),
            source_ref=candidate.source_ref or f"候选 {candidate.candidate_id}",
            text=overrides.get("text", candidate.text),
            tags=overrides.get("tags", candidate.tags),
            background=False,
        )
        now = datetime.now(timezone.utc)

        def _mark(c: KBCandidate) -> None:
            c.status = CandidateStatus.APPROVED
            c.doc_id = doc.doc_id
            c.reviewed_by = reviewer
            c.reviewed_at = now

        await self._candidates.update(candidate_id, _mark)
        logger.info("kb.candidate_approved", candidate_id=candidate_id,
                    doc_id=doc.doc_id, reviewer=reviewer)
        return await self._candidates.get_by_id(candidate_id), doc  # type: ignore[return-value]

    async def reject_candidate(self, candidate_id: str, reviewer: str,
                               review_note: str) -> KBCandidate:
        """驳回候选（pending → rejected，终态）。"""
        candidate = await self._candidates.get_by_id(candidate_id)
        if candidate is None:
            raise NotFoundError(f"候选知识不存在：{candidate_id}")
        if candidate.status is not CandidateStatus.PENDING:
            raise ConflictError(
                f"候选已处于终态 {candidate.status.value}，不可重复审核",
                details={"candidate_id": candidate_id,
                         "status": candidate.status.value},
            )
        now = datetime.now(timezone.utc)

        def _mark(c: KBCandidate) -> None:
            c.status = CandidateStatus.REJECTED
            c.review_note = review_note
            c.reviewed_by = reviewer
            c.reviewed_at = now

        await self._candidates.update(candidate_id, _mark)
        logger.info("kb.candidate_rejected", candidate_id=candidate_id,
                    reviewer=reviewer)
        return await self._candidates.get_by_id(candidate_id)  # type: ignore[return-value]
