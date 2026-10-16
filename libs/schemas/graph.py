"""知识图谱领域模型（mock GraphRAG）。

实体以 name 为主键（mock 规模下名称唯一）；边按 (source,target,relation) 去重累计权重。
社区按井号聚合生成，供 GraphRAG 查询时做摘要兜底。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EntityType(str, Enum):
    """实体类型（规则抽取）。"""

    WELL = "井"
    RISK = "风险"
    CONCEPT = "概念"
    DOC = "文档"


class GraphNode(BaseModel):
    """图谱实体。"""

    name: str
    entity_type: EntityType
    description: str = ""
    sources: list[str] = Field(default_factory=list, description="来源 doc_id")
    degree: int = 0


class GraphEdge(BaseModel):
    """图谱边（实体间共现关系）。"""

    source: str
    target: str
    relation: str
    weight: float = 1.0
    doc_id: str = ""


class GraphCommunity(BaseModel):
    """社区（按井号聚合的实体簇 + 全局安全社区）。"""

    community_id: str = Field(default_factory=lambda: f"com-{uuid.uuid4().hex[:8]}")
    title: str
    summary: str = ""
    members: list[str] = Field(default_factory=list)
    size: int = 0


class BuildStatus(str, Enum):
    """图谱重建任务状态机：idle → building → done / failed。"""

    IDLE = "idle"
    BUILDING = "building"
    DONE = "done"
    FAILED = "failed"


class GraphBuildMeta(BaseModel):
    """最近一次重建任务的元信息。"""

    status: BuildStatus = BuildStatus.IDLE
    version: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
