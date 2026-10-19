"""知识库领域模型：文档 + 分块 + 索引状态机。

文档状态机：pending → indexing → ready / failed（failed 可 reindex 重试）。
文档删除级联删除其全部分块；检索只命中 ready 文档的分块。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IndexStatus(str, Enum):
    """文档索引状态。"""

    PENDING = "pending"      # 已上传，待索引
    INDEXING = "indexing"    # 分块索引中
    READY = "ready"          # 可检索
    FAILED = "failed"        # 索引失败（可重建）


class KBDocument(BaseModel):
    """知识库文档（规程 / 预案 / 案例 / 其他）。"""

    doc_id: str = Field(default_factory=lambda: _uid("kb"))
    title: str
    doc_type: str = "其他"
    source_ref: str = ""
    text: str
    tags: list[str] = Field(default_factory=list)
    status: IndexStatus = IndexStatus.PENDING
    chunk_count: int = 0
    error: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class KBChunk(BaseModel):
    """文档分块（检索的最小单元）。"""

    chunk_id: str = Field(default_factory=lambda: _uid("chk"))
    doc_id: str
    seq: int
    text: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


class CandidateStatus(str, Enum):
    """候选知识审核状态机：pending → approved / rejected（终态）。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class KBCandidate(BaseModel):
    """候选知识条目（自进化沉淀队列）。

    由运行数据自动沉淀生成（工单闭环 / 高频告警 / trace 手动沉淀），
    必须经审核采纳后才正式入库——LLM/规则生成内容不直接进知识库。
    (source_type, source_id) 为幂等键，同一来源不重复生成。
    """

    candidate_id: str = Field(default_factory=lambda: _uid("cand"))
    source_type: str           # workorder / alert_dedup / trace
    source_id: str             # 来源实体 id（工单号 / 去重键 / trace_id）
    title: str
    doc_type: str = "案例"
    source_ref: str = ""
    text: str
    tags: list[str] = Field(default_factory=list)
    status: CandidateStatus = CandidateStatus.PENDING
    doc_id: str | None = None  # 采纳后生成的文档 id
    review_note: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime = Field(default_factory=_utcnow)
