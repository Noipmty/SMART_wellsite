"""知识图谱仓储：节点/边/社区/构建元信息的内存实现（真实部署换 Neo4j）。"""

from __future__ import annotations

import asyncio

from libs.schemas.graph import (
    EntityType,
    GraphBuildMeta,
    GraphCommunity,
    GraphEdge,
    GraphNode,
)
from repositories.base import BaseRepository


class GraphRepository(BaseRepository[GraphNode]):
    """协程安全的内存图存储；节点以 name 为主键。"""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._communities: dict[str, GraphCommunity] = {}
        self._meta = GraphBuildMeta()
        self._lock = asyncio.Lock()

    async def count(self) -> int:
        async with self._lock:
            return len(self._nodes)

    # ---------------- 节点 ----------------

    async def get_node(self, name: str) -> GraphNode | None:
        async with self._lock:
            return self._nodes.get(name)

    async def query_nodes(
        self,
        entity_type: EntityType | None = None,
        keyword: str | None = None,
    ) -> list[GraphNode]:
        async with self._lock:
            nodes = list(self._nodes.values())
        if entity_type:
            nodes = [n for n in nodes if n.entity_type is entity_type]
        if keyword:
            nodes = [n for n in nodes if keyword in n.name]
        nodes.sort(key=lambda n: (-n.degree, n.name))
        return nodes

    # ---------------- 边 / 邻居 ----------------

    async def edges_of(self, name: str) -> list[GraphEdge]:
        async with self._lock:
            edges = [e for e in self._edges
                     if e.source == name or e.target == name]
        edges.sort(key=lambda e: e.weight, reverse=True)
        return edges

    async def list_edges(self) -> list[GraphEdge]:
        async with self._lock:
            return list(self._edges)

    # ---------------- 社区 ----------------

    async def list_communities(self) -> list[GraphCommunity]:
        async with self._lock:
            items = list(self._communities.values())
        items.sort(key=lambda c: c.size, reverse=True)
        return items

    async def get_community(self, community_id: str) -> GraphCommunity | None:
        async with self._lock:
            return self._communities.get(community_id)

    # ---------------- 构建 ----------------

    async def replace_graph(
        self,
        nodes: dict[str, GraphNode],
        edges: list[GraphEdge],
        communities: dict[str, GraphCommunity],
    ) -> None:
        """原子替换整图（重建幂等语义）。"""
        async with self._lock:
            self._nodes = nodes
            self._edges = edges
            self._communities = communities

    async def get_meta(self) -> GraphBuildMeta:
        async with self._lock:
            return self._meta.model_copy()

    async def set_meta(self, patch) -> GraphBuildMeta:
        async with self._lock:
            patch(self._meta)
            return self._meta.model_copy()
