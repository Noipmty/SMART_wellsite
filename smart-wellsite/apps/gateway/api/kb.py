"""知识库管理 API：文档上传、分块索引状态机、检索测试、删除。

索引状态机：pending → indexing → ready / failed（failed 可 reindex）。
检索仅命中 ready 文档的分块；删除文档级联删除其分块。
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field

from apps.container import Container
from libs.api import (
    BadRequestError,
    NotFoundError,
    Page,
    PageParams,
    ServiceUnavailableError,
    pagination_params,
)
from libs.schemas.kb import (
    CandidateStatus,
    IndexStatus,
    KBCandidate,
    KBChunk,
    KBDocument,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/kb", tags=["knowledge-base"])

DocType = Literal["规程", "预案", "案例", "其他"]


def _get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise ServiceUnavailableError("服务未就绪")
    return container


class DocumentView(BaseModel):
    """文档列表视图（正文截断为摘要，控制响应体大小）。"""

    doc_id: str
    title: str
    doc_type: str
    source_ref: str
    summary: str
    tags: list[str]
    status: IndexStatus
    chunk_count: int
    error: str | None = None
    created_at: str
    updated_at: str

    @classmethod
    def from_doc(cls, d: KBDocument) -> "DocumentView":
        return cls(
            doc_id=d.doc_id, title=d.title, doc_type=d.doc_type,
            source_ref=d.source_ref, summary=d.text[:80], tags=d.tags,
            status=d.status, chunk_count=d.chunk_count, error=d.error,
            created_at=d.created_at.isoformat(),
            updated_at=d.updated_at.isoformat(),
        )


class DocumentDetailView(BaseModel):
    """文档详情视图（含全部 chunk 列表）。"""

    document: DocumentView
    text: str
    chunks: list[KBChunk]


class CreateDocumentRequest(BaseModel):
    """上传文档请求体。"""

    title: str = Field(min_length=1, max_length=200)
    doc_type: DocType = "其他"
    source_ref: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)
    tags: list[str] = Field(default_factory=list, max_length=20)


class SearchRequest(BaseModel):
    """检索测试请求体。"""

    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=10)
    doc_type: DocType | None = None


class SearchHit(BaseModel):
    """单条检索命中。"""

    id: str
    chunk_id: str
    source_ref: str
    type: str
    title: str
    text: str
    tags: list[str]
    score: int


@router.get("/documents", response_model=Page[DocumentView])
async def list_documents(
    request: Request,
    params: PageParams = Depends(pagination_params),
    status: IndexStatus | None = Query(None, description="按索引状态过滤"),
    doc_type: DocType | None = Query(None, description="按文档类型过滤"),
) -> Page[DocumentView]:
    """文档列表（按创建时间倒序，分页）。"""
    container = _get_container(request)
    docs = await container.kb_doc_repo.query(status=status, doc_type=doc_type)
    items = [DocumentView.from_doc(d)
             for d in docs[params.offset : params.offset + params.limit]]
    return Page.build(items, total=len(docs), params=params)


@router.post("/documents", response_model=DocumentView, status_code=201)
async def create_document(body: CreateDocumentRequest,
                          request: Request) -> DocumentView:
    """上传文档：落库 PENDING 并后台异步分块索引（轮询详情可得终态）。"""
    container = _get_container(request)
    doc = await container.kb_service.create_document(
        title=body.title, doc_type=body.doc_type,
        source_ref=body.source_ref, text=body.text, tags=body.tags,
    )
    logger.info("kb.api_doc_created", doc_id=doc.doc_id, title=doc.title)
    return DocumentView.from_doc(doc)


@router.get("/documents/{doc_id}", response_model=DocumentDetailView)
async def get_document(doc_id: str, request: Request) -> DocumentDetailView:
    """文档详情：含正文与全部 chunk（索引状态/分块结果可见）。"""
    container = _get_container(request)
    doc = await container.kb_doc_repo.get_by_id(doc_id)
    if doc is None:
        raise NotFoundError(f"知识库文档不存在：{doc_id}")
    chunks = await container.kb_chunk_repo.list_by_doc(doc_id)
    return DocumentDetailView(
        document=DocumentView.from_doc(doc), text=doc.text, chunks=chunks,
    )


@router.post("/documents/{doc_id}/reindex", response_model=DocumentView)
async def reindex_document(doc_id: str, request: Request) -> DocumentView:
    """重建索引（幂等）：清空旧分块重新切分，failed/ready 均可。"""
    container = _get_container(request)
    doc = await container.kb_service.reindex(doc_id)
    return DocumentView.from_doc(doc)


class UpdateDocumentRequest(BaseModel):
    """更新文档请求体（至少一项）。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=20000)


@router.patch("/documents/{doc_id}", response_model=DocumentView)
async def update_document(doc_id: str, body: UpdateDocumentRequest,
                          request: Request) -> DocumentView:
    """更新文档标题/正文；正文变更同步重建索引。"""
    if body.title is None and body.text is None:
        raise BadRequestError("title 与 text 至少提供一项")
    container = _get_container(request)
    doc = await container.kb_service.update_document(
        doc_id, title=body.title, text=body.text
    )
    logger.info("kb.api_doc_updated", doc_id=doc_id)
    return DocumentView.from_doc(doc)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: str, request: Request) -> Response:
    """删除文档并级联删除其全部分块；不存在返回统一 404。"""
    container = _get_container(request)
    await container.kb_service.delete_document(doc_id)
    return Response(status_code=204)


@router.post("/search", response_model=list[SearchHit])
async def search_knowledge(body: SearchRequest, request: Request) -> list[SearchHit]:
    """检索测试：对 ready 文档分块做关键词重合度评分，返回 top_k 命中。"""
    container = _get_container(request)
    hits = await container.kb_service.search(
        body.query, top_k=body.top_k, doc_type=body.doc_type
    )
    logger.info("kb.api_search", query=body.query, hits=len(hits))
    return [SearchHit(**h) for h in hits]


# ---------------- 候选沉淀队列（自进化管道） ----------------

class ApproveRequest(BaseModel):
    """采纳候选：审核人必填，可选编辑标题/正文/tags/类型。"""

    reviewer: str = Field(min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    text: str | None = Field(default=None, min_length=1, max_length=20000)
    tags: list[str] | None = Field(default=None, max_length=20)
    doc_type: DocType | None = None


class RejectRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=64)
    review_note: str = Field(min_length=1, max_length=500)


class DistillTraceRequest(BaseModel):
    """从链路追踪手动沉淀问答候选。"""

    trace_id: str = Field(min_length=1)


class ApproveResult(BaseModel):
    candidate: KBCandidate
    document: DocumentView
    graph_rebuild: str = "triggered"


@router.get("/candidates", response_model=Page[KBCandidate])
async def list_candidates(
    request: Request,
    params: PageParams = Depends(pagination_params),
    status: CandidateStatus | None = Query(None, description="按审核状态过滤"),
) -> Page[KBCandidate]:
    """候选队列（按创建时间倒序，分页）。"""
    container = _get_container(request)
    candidates = await container.kb_candidate_repo.query(status=status)
    items = candidates[params.offset : params.offset + params.limit]
    return Page.build(items, total=len(candidates), params=params)


@router.post("/candidates/distill", response_model=KBCandidate, status_code=201)
async def distill_trace(body: DistillTraceRequest, request: Request) -> KBCandidate:
    """从一条 trace 手动沉淀问答候选（幂等：同一 trace 不重复生成）。"""
    container = _get_container(request)
    record = await container.trace_repo.get(body.trace_id)
    if record is None:
        raise NotFoundError(f"链路不存在：{body.trace_id}")
    if not record.results:
        raise BadRequestError(
            f"链路无节点结论，无可沉淀内容：{body.trace_id}")
    best = max(record.results, key=lambda r: r.confidence)
    evidence_text = "；".join(
        f"{e.metric}={e.value}" for r in record.results
        for e in r.evidence[:2] if e.value is not None
    )
    candidate, created = await container.kb_service.submit_candidate(
        source_type="trace", source_id=record.trace_id,
        title=f"问答沉淀：{record.question[:30]}",
        doc_type="案例",
        source_ref=f"链路 {record.trace_id}",
        text=(f"问题：{record.question}\n结论：{best.conclusion}\n"
              f"依据：{evidence_text or best.suggestion or '见节点结论'}"),
    )
    if not created:
        logger.info("kb.api_distill_dedup", trace_id=record.trace_id)
    return candidate


@router.post("/candidates/{candidate_id}/approve", response_model=ApproveResult)
async def approve_candidate(candidate_id: str, body: ApproveRequest,
                            request: Request) -> ApproveResult:
    """采纳候选：可选编辑后正式入库（READY），并触发图谱增量重建。"""
    container = _get_container(request)
    overrides = body.model_dump(exclude_none=True, exclude={"reviewer"})
    candidate, doc = await container.kb_service.approve_candidate(
        candidate_id, body.reviewer, overrides or None
    )
    await container.graph_service.rebuild(background=True)
    logger.info("kb.api_candidate_approved", candidate_id=candidate_id,
                doc_id=doc.doc_id, reviewer=body.reviewer)
    return ApproveResult(candidate=candidate,
                         document=DocumentView.from_doc(doc))


@router.post("/candidates/{candidate_id}/reject", response_model=KBCandidate)
async def reject_candidate(candidate_id: str, body: RejectRequest,
                           request: Request) -> KBCandidate:
    """驳回候选（终态，附驳回原因）。"""
    container = _get_container(request)
    return await container.kb_service.reject_candidate(
        candidate_id, body.reviewer, body.review_note
    )
