"""知识图谱服务：规则抽取实体/共现边、按井聚合社区、后台增量重建任务。

mock 抽取规则（真实部署换 LLM 抽取 + Neo4j 写入，接口契约不变）：
- 实体：井号正则 W-\\d+ → 井；风险词表 → 风险；其余领域关键词 → 概念；
  文档标题 → 文档（类型即 doc_type 语义载体）
- 边：chunk 内共现——井↔概念/风险（涉及）、概念/风险↔文档（出自）、井↔文档（记载于）；
  同一 (source,target,relation) 累计权重（共现次数）
- 社区：每井一簇（井 + 相邻实体），无井实体归入全局安全社区；摘要为模板文本

重建任务状态机：idle → building → done / failed；replace_graph 原子替换保证幂等，
KB 文档新增/删除后 rebuild 即体现增量。
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone

import structlog

from libs.api.errors import ConflictError, NotFoundError
from libs.schemas.graph import (
    BuildStatus,
    EntityType,
    GraphCommunity,
    GraphEdge,
    GraphNode,
)
from libs.schemas.kb import IndexStatus
from repositories.graph_repo import GraphRepository
from repositories.kb_repo import KBChunkRepository, KBDocumentRepository
from services.kb_service import DOMAIN_KEYWORDS

logger = structlog.get_logger(__name__)

_WELL_RE = re.compile(r"W-\d+")
_RISK_WORDS = frozenset({
    "H2S", "硫化氢", "井涌", "违规闯入", "安全帽", "动火", "结蜡", "水合物",
})


def _classify(term: str) -> EntityType:
    if _WELL_RE.fullmatch(term):
        return EntityType.WELL
    if term in _RISK_WORDS:
        return EntityType.RISK
    return EntityType.CONCEPT


class GraphService:
    """知识图谱领域服务（每个依赖容器持有一个实例）。"""

    def __init__(self, repo: GraphRepository,
                 doc_repo: KBDocumentRepository,
                 chunk_repo: KBChunkRepository) -> None:
        self._repo = repo
        self._docs = doc_repo
        self._chunks = chunk_repo
        self._build_task: asyncio.Task | None = None

    # ---------------- 抽取与重建 ----------------

    async def _extract(self) -> tuple[dict[str, GraphNode], list[GraphEdge],
                                      dict[str, GraphCommunity]]:
        docs = await self._docs.query(status=IndexStatus.READY)
        nodes: dict[str, GraphNode] = {}
        edge_weights: dict[tuple[str, str, str], GraphEdge] = {}

        def touch(name: str, etype: EntityType, doc_id: str, desc: str = "") -> None:
            node = nodes.get(name)
            if node is None:
                nodes[name] = GraphNode(name=name, entity_type=etype,
                                        description=desc, sources=[doc_id])
            elif doc_id not in node.sources:
                node.sources.append(doc_id)

        def link(a: str, b: str, relation: str, doc_id: str) -> None:
            if a == b:
                return
            key = (a, b, relation)
            edge = edge_weights.get(key)
            if edge is None:
                edge_weights[key] = GraphEdge(source=a, target=b,
                                              relation=relation, doc_id=doc_id)
            else:
                edge.weight += 1.0

        for doc in docs:
            touch(doc.title, EntityType.DOC, doc.doc_id,
                  desc=f"{doc.doc_type}：{doc.source_ref}")
            chunks = await self._chunks.list_by_doc(doc.doc_id)
            for chunk in chunks:
                wells = set(_WELL_RE.findall(chunk.text))
                terms = {kw for kw in DOMAIN_KEYWORDS if kw in chunk.text}
                terms.update(t for t in chunk.tags
                             if t in DOMAIN_KEYWORDS or _WELL_RE.fullmatch(t))
                terms.update(w for w in wells)
                for well in wells:
                    touch(well, EntityType.WELL, doc.doc_id)
                    link(well, doc.title, "记载于", doc.doc_id)
                for term in terms - wells:
                    touch(term, _classify(term), doc.doc_id)
                    link(term, doc.title, "出自", doc.doc_id)
                for well in wells:
                    for term in terms - wells:
                        link(well, term, "涉及", doc.doc_id)

        edges = list(edge_weights.values())
        # 度数回填
        for edge in edges:
            if edge.source in nodes:
                nodes[edge.source].degree += 1
            if edge.target in nodes:
                nodes[edge.target].degree += 1

        communities = self._build_communities(nodes, edges)
        return nodes, edges, communities

    @staticmethod
    def _build_communities(nodes: dict[str, GraphNode],
                           edges: list[GraphEdge]) -> dict[str, GraphCommunity]:
        neighbors: dict[str, set[str]] = {}
        for edge in edges:
            neighbors.setdefault(edge.source, set()).add(edge.target)
            neighbors.setdefault(edge.target, set()).add(edge.source)

        claimed: set[str] = set()
        communities: dict[str, GraphCommunity] = {}
        wells = [n for n in nodes.values() if n.entity_type is EntityType.WELL]
        for well in sorted(wells, key=lambda n: n.name):
            members = sorted({well.name} | neighbors.get(well.name, set()))
            claimed.update(members)
            risks = [m for m in members
                     if nodes[m].entity_type is EntityType.RISK]
            summary = (f"{well.name} 井簇：关联 {len(members)} 个实体"
                       f"（风险 {len(risks)} 项"
                       f"{'：' + '、'.join(risks) if risks else ''}）")
            com = GraphCommunity(title=f"{well.name} 井簇", summary=summary,
                                 members=members, size=len(members))
            communities[com.community_id] = com

        rest = sorted(set(nodes) - claimed)
        if rest:
            com = GraphCommunity(
                title="全局安全社区",
                summary=f"跨井通用安全/工艺概念 {len(rest)} 项，"
                        "供无明确井号的问题做社区摘要兜底",
                members=rest, size=len(rest))
            communities[com.community_id] = com
        return communities

    async def rebuild(self, *, background: bool = True) -> None:
        """触发增量重建（幂等）；building 中重复触发抛 409。"""
        meta = await self._repo.get_meta()
        if meta.status is BuildStatus.BUILDING:
            raise ConflictError("图谱重建任务进行中，请稍后查询状态",
                                details={"version": meta.version})
        if background:
            self._build_task = asyncio.create_task(self._do_build())
        else:
            await self._do_build()

    async def _do_build(self) -> None:
        meta = await self._repo.get_meta()
        version = meta.version + 1

        def _start(m) -> None:
            m.status = BuildStatus.BUILDING
            m.version = version
            m.started_at = datetime.now(timezone.utc)
            m.finished_at = None
            m.error = None

        await self._repo.set_meta(_start)
        logger.info("graph.build_started", version=version)
        try:
            nodes, edges, communities = await self._extract()
            await self._repo.replace_graph(nodes, edges, communities)

            def _done(m) -> None:
                m.status = BuildStatus.DONE
                m.finished_at = datetime.now(timezone.utc)
                m.node_count = len(nodes)
                m.edge_count = len(edges)
                m.community_count = len(communities)

            await self._repo.set_meta(_done)
            logger.info("graph.build_done", version=version,
                        nodes=len(nodes), edges=len(edges),
                        communities=len(communities))
        except Exception as exc:  # noqa: BLE001 - 失败落 meta 可查询
            logger.exception("graph.build_failed", version=version)

            def _fail(m) -> None:
                m.status = BuildStatus.FAILED
                m.finished_at = datetime.now(timezone.utc)
                m.error = str(exc)[:200]

            await self._repo.set_meta(_fail)
            raise

    # ---------------- 查询 ----------------

    async def neighbors(self, name: str) -> tuple[GraphNode, list[dict]]:
        """一跳邻居：按边权倒序返回邻接实体与关系。"""
        node = await self._repo.get_node(name)
        if node is None:
            raise NotFoundError(f"图谱实体不存在：{name}")
        edges = await self._repo.edges_of(name)
        result: list[dict] = []
        for edge in edges:
            other = edge.target if edge.source == name else edge.source
            other_node = await self._repo.get_node(other)
            if other_node is None:
                continue
            result.append({
                "node": other_node,
                "relation": edge.relation,
                "direction": "out" if edge.source == name else "in",
                "weight": edge.weight,
            })
        return node, result
