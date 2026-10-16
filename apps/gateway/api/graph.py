"""知识图谱 API：统计、实体/邻居/社区查询、后台增量重建任务。"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from apps.container import Container
from libs.api import (
    NotFoundError,
    Page,
    PageParams,
    ServiceUnavailableError,
    pagination_params,
)
from libs.schemas.graph import EntityType, GraphBuildMeta, GraphCommunity, GraphNode

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/graph", tags=["knowledge-graph"])


def _get_container(request: Request) -> Container:
    container = getattr(request.app.state, "container", None)
    if container is None:
        raise ServiceUnavailableError("服务未就绪")
    return container


class GraphStats(BaseModel):
    """图谱总览统计。"""

    status: str
    version: int
    node_count: int
    edge_count: int
    community_count: int
    built_at: str | None = None


class NeighborItem(BaseModel):
    """单条邻接关系。"""

    node: GraphNode
    relation: str
    direction: str
    weight: float


class NeighborsView(BaseModel):
    """实体一跳邻居视图。"""

    entity: GraphNode
    neighbors: list[NeighborItem]


class RebuildAccepted(BaseModel):
    """重建任务受理回执（202）。"""

    status: str
    version: int
    message: str


@router.get("/stats", response_model=GraphStats)
async def graph_stats(request: Request) -> GraphStats:
    """图谱统计：节点/边/社区计数 + 最近构建版本与状态。"""
    container = _get_container(request)
    meta = await container.graph_repo.get_meta()
    return GraphStats(
        status=meta.status.value, version=meta.version,
        node_count=meta.node_count, edge_count=meta.edge_count,
        community_count=meta.community_count,
        built_at=meta.finished_at.isoformat() if meta.finished_at else None,
    )


@router.get("/entities", response_model=Page[GraphNode])
async def list_entities(
    request: Request,
    params: PageParams = Depends(pagination_params),
    entity_type: EntityType | None = Query(None, description="按类型过滤：井/风险/概念/文档"),
    q: str | None = Query(None, description="名称模糊匹配"),
) -> Page[GraphNode]:
    """实体列表（按度数倒序，分页）。"""
    container = _get_container(request)
    nodes = await container.graph_repo.query_nodes(entity_type=entity_type,
                                                   keyword=q)
    items = nodes[params.offset : params.offset + params.limit]
    return Page.build(items, total=len(nodes), params=params)


@router.get("/entities/{name}/neighbors", response_model=NeighborsView)
async def entity_neighbors(name: str, request: Request) -> NeighborsView:
    """实体一跳邻居（按边权倒序）；实体不存在返回统一 404。"""
    container = _get_container(request)
    node, neighbors = await container.graph_service.neighbors(name)
    return NeighborsView(
        entity=node,
        neighbors=[NeighborItem(**n) for n in neighbors],
    )


@router.get("/communities", response_model=Page[GraphCommunity])
async def list_communities(
    request: Request,
    params: PageParams = Depends(pagination_params),
) -> Page[GraphCommunity]:
    """社区列表（按规模倒序，分页）。"""
    container = _get_container(request)
    communities = await container.graph_repo.list_communities()
    items = communities[params.offset : params.offset + params.limit]
    return Page.build(items, total=len(communities), params=params)


@router.get("/communities/{community_id}", response_model=GraphCommunity)
async def get_community(community_id: str, request: Request) -> GraphCommunity:
    """社区详情（含成员与摘要）；不存在返回统一 404。"""
    container = _get_container(request)
    community = await container.graph_repo.get_community(community_id)
    if community is None:
        raise NotFoundError(f"图谱社区不存在：{community_id}")
    return community


@router.post("/rebuild", response_model=RebuildAccepted, status_code=202)
async def trigger_rebuild(request: Request) -> RebuildAccepted:
    """触发后台增量重建（幂等）；building 中重复触发返回统一 409。"""
    container = _get_container(request)
    meta = await container.graph_repo.get_meta()
    next_version = meta.version + 1
    await container.graph_service.rebuild(background=True)
    logger.info("graph.api_rebuild", version=next_version)
    return RebuildAccepted(status="building", version=next_version,
                           message="重建任务已受理，轮询 /rebuild/status 获取终态")


@router.get("/rebuild/status", response_model=GraphBuildMeta)
async def rebuild_status(request: Request) -> GraphBuildMeta:
    """查询最近一次重建任务的状态与计数。"""
    container = _get_container(request)
    return await container.graph_repo.get_meta()
