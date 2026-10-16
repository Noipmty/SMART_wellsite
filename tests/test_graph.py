"""阶段 6：知识图谱测试（规则抽取/社区聚合/重建状态机/API）。"""

import time

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from libs.api.errors import ConflictError, NotFoundError
from libs.schemas.graph import BuildStatus, EntityType
from repositories.graph_repo import GraphRepository
from repositories.kb_repo import KBChunkRepository, KBDocumentRepository
from services.graph_service import GraphService
from services.kb_service import KBService


async def _built_service():
    docs, chunks = KBDocumentRepository(), KBChunkRepository()
    kb = KBService(docs, chunks)
    await kb.seed_defaults()
    repo = GraphRepository()
    svc = GraphService(repo, docs, chunks)
    await svc.rebuild(background=False)
    return svc, repo, kb


# ---------------- 服务层 ----------------

@pytest.mark.asyncio
async def test_build_extracts_entities_edges_communities():
    svc, repo, kb = await _built_service()
    meta = await repo.get_meta()
    assert meta.status is BuildStatus.DONE
    assert meta.version == 1
    assert meta.node_count > 0 and meta.edge_count > 0
    assert meta.community_count >= 1

    # W-3 井实体来自种子案例；风险类实体被正确归类
    w3 = await repo.get_node("W-3")
    assert w3 is not None and w3.entity_type is EntityType.WELL
    assert w3.degree >= 1

    nodes = await repo.query_nodes(entity_type=EntityType.RISK)
    assert {n.name for n in nodes} & {"H2S", "井涌"}

    docs_nodes = await repo.query_nodes(entity_type=EntityType.DOC)
    assert len(docs_nodes) == 5  # 种子 5 篇文档

    communities = await repo.list_communities()
    w3_com = next(c for c in communities if "W-3" in c.title)
    assert "W-3" in w3_com.members
    member_types = set()
    for m in w3_com.members:
        member = await repo.get_node(m)
        member_types.add(member.entity_type)
    assert EntityType.CONCEPT in member_types


@pytest.mark.asyncio
async def test_neighbors_ordered_by_weight_and_404():
    svc, repo, kb = await _built_service()
    node, neighbors = await svc.neighbors("W-3")
    assert node.name == "W-3"
    assert neighbors
    weights = [n["weight"] for n in neighbors]
    assert weights == sorted(weights, reverse=True)
    assert all(n["relation"] in ("涉及", "记载于") for n in neighbors)
    assert {n["direction"] for n in neighbors} <= {"in", "out"}

    with pytest.raises(NotFoundError):
        await svc.neighbors("W-99")


@pytest.mark.asyncio
async def test_rebuild_increment_reflects_kb_changes():
    """新增 KB 文档后重建：实体计数增加；删除后重建：计数回落（幂等）。"""
    svc, repo, kb = await _built_service()
    before = (await repo.get_meta()).node_count

    doc = await kb.create_document(
        title="W-9 井涌处置案例", doc_type="案例", source_ref="C-9",
        text="W-9 发生井涌，泥浆密度突降，立即降低钻压循环观察。",
        background=False)
    await svc.rebuild(background=False)
    meta = await repo.get_meta()
    assert meta.version == 2
    assert meta.node_count > before
    assert await repo.get_node("W-9") is not None

    await kb.delete_document(doc.doc_id)
    await svc.rebuild(background=False)
    meta2 = await repo.get_meta()
    assert meta2.node_count == before
    assert await repo.get_node("W-9") is None


@pytest.mark.asyncio
async def test_rebuild_conflict_while_building():
    svc, repo, kb = await _built_service()

    def _building(m) -> None:
        m.status = BuildStatus.BUILDING

    await repo.set_meta(_building)
    with pytest.raises(ConflictError):
        await svc.rebuild(background=False)


# ---------------- API 层 ----------------

def _wait_build_done(client, retries: int = 50) -> dict:
    for _ in range(retries):
        meta = client.get("/api/v1/graph/rebuild/status").json()
        if meta["status"] == "done":
            return meta
        time.sleep(0.02)
    raise AssertionError("图谱重建超时")


def test_graph_api_stats_entities_neighbors_communities():
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/graph/stats")
        assert r.status_code == 200
        stats = r.json()
        assert stats["status"] == "done" and stats["version"] >= 1
        assert stats["node_count"] > 0 and stats["community_count"] >= 1

        r2 = client.get("/api/v1/graph/entities",
                        params={"entity_type": "井"})
        assert r2.status_code == 200
        assert r2.json()["total"] >= 1
        assert all(n["entity_type"] == "井" for n in r2.json()["items"])

        r3 = client.get("/api/v1/graph/entities", params={"q": "W-3"})
        assert any(n["name"] == "W-3" for n in r3.json()["items"])

        r4 = client.get("/api/v1/graph/entities/W-3/neighbors")
        assert r4.status_code == 200
        body = r4.json()
        assert body["entity"]["name"] == "W-3"
        assert body["neighbors"]
        assert {"node", "relation", "direction", "weight"} <= \
            body["neighbors"][0].keys()

        r5 = client.get("/api/v1/graph/communities")
        assert r5.status_code == 200
        com = r5.json()["items"][0]
        assert {"community_id", "title", "summary", "members", "size"} <= com.keys()
        r6 = client.get(f"/api/v1/graph/communities/{com['community_id']}")
        assert r6.status_code == 200
        assert r6.json()["summary"]


def test_graph_api_rebuild_flow_and_errors():
    with TestClient(create_app()) as client:
        # 触发重建 → 202 → 轮询至 done
        r = client.post("/api/v1/graph/rebuild")
        assert r.status_code == 202
        assert r.json()["status"] == "building"
        meta = _wait_build_done(client)
        assert meta["version"] >= 2
        assert meta["node_count"] > 0

        # 404：实体 / 社区不存在
        r2 = client.get("/api/v1/graph/entities/W-99/neighbors")
        assert r2.status_code == 404
        assert r2.json()["error"]["code"] == "NOT_FOUND"

        r3 = client.get("/api/v1/graph/communities/com-不存在")
        assert r3.status_code == 404

        # 新增 KB 文档 → 重建 → 新井实体可查（增量闭环）
        client.post("/api/v1/kb/documents", json={
            "title": "W-8 结蜡处置规程", "doc_type": "规程",
            "source_ref": "《采气规程》9.9",
            "text": "W-8 节流前压力升高且产量下降，排查结蜡与水合物。",
        })
        client.post("/api/v1/graph/rebuild")
        _wait_build_done(client)
        r4 = client.get("/api/v1/graph/entities/W-8/neighbors")
        assert r4.status_code == 200
        assert any(n["node"]["entity_type"] == "风险"
                   for n in r4.json()["neighbors"])
