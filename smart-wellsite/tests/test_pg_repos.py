"""PostgreSQL 仓储集成测试（真实库，需本地 docker wellsite-postgres）。

默认跳过：RUN_PG_TESTS=1 时启用。用例间以 TRUNCATE 隔离，不污染种子数据
（种子由容器启动时按空库守卫灌入，测试后重启网关即恢复）。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PG_TESTS") != "1",
    reason="PG 集成测试需 RUN_PG_TESTS=1 且本地 wellsite-postgres 运行中",
)


@pytest.fixture
async def pg_repos():
    from libs.db import close_connections, get_pg_pool
    from repositories.pg import PgRepositories, run_ddl

    pool = await get_pg_pool()
    await run_ddl(pool)
    repos = PgRepositories(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "TRUNCATE app_alerts, app_work_orders, app_kb_documents,"
            " app_kb_chunks, app_kb_candidates, app_graph_nodes,"
            " app_graph_edges, app_graph_communities, app_graph_meta,"
            " app_traces"
        )
    yield repos
    await close_connections()


async def test_alert_roundtrip_and_query(pg_repos):
    from libs.schemas.alerts import Alert, AlertStatus

    repo = pg_repos.alert_repo
    alert = Alert(level="预警", source="data_collector", cause="供液不足", scope="W-3")
    await repo.save(alert)

    loaded = await repo.get_by_id(alert.alert_id)
    assert loaded is not None and loaded.cause == "供液不足"

    def _ack(a: Alert) -> None:
        a.status = AlertStatus.ACKNOWLEDGED
        a.acknowledged_by = "测试员"

    updated = await repo.update(alert.alert_id, _ack)
    assert updated is not None and updated.status is AlertStatus.ACKNOWLEDGED

    hit = await repo.query(status=AlertStatus.ACKNOWLEDGED, level="预警", well_id="W-3")
    assert [a.alert_id for a in hit] == [alert.alert_id]
    assert await repo.query(status=AlertStatus.ACTIVE) == []


async def test_work_order_update_persists(pg_repos):
    from libs.schemas.alerts import WorkOrder, WorkOrderStatus

    repo = pg_repos.order_repo
    order = WorkOrder(alert_id="alt-x", title="[预警] 测试", priority="预警", well_id="W-1")
    await repo.save(order)

    def _assign(o: WorkOrder) -> None:
        o.status = WorkOrderStatus.PROCESSING
        o.assignee = "张工"

    await repo.update(order.order_id, _assign)
    loaded = await repo.get_by_id(order.order_id)
    assert loaded is not None
    assert loaded.status is WorkOrderStatus.PROCESSING and loaded.assignee == "张工"
    rows = await repo.query(assignee="张工")
    assert len(rows) == 1


async def test_kb_doc_chunk_cascade_and_candidate_idempotency(pg_repos):
    from libs.schemas.kb import IndexStatus, KBChunk, KBDocument

    doc_repo, chunk_repo, cand_repo = (
        pg_repos.kb_doc_repo, pg_repos.kb_chunk_repo, pg_repos.kb_candidate_repo)
    doc = KBDocument(title="测试文档", text="正文", status=IndexStatus.READY)
    await doc_repo.save(doc)
    await chunk_repo.save_all([
        KBChunk(doc_id=doc.doc_id, seq=0, text="块一"),
        KBChunk(doc_id=doc.doc_id, seq=1, text="块二"),
    ])
    assert len(await chunk_repo.list_by_doc(doc.doc_id)) == 2
    assert len(await chunk_repo.list_ready({doc.doc_id})) == 2
    assert await chunk_repo.delete_by_doc(doc.doc_id) == 2
    assert await doc_repo.delete(doc.doc_id) is True

    from services.kb_service import KBService

    svc = KBService(doc_repo, chunk_repo, cand_repo)
    c1, created1 = await svc.submit_candidate("workorder", "ord-1", "t", "正文")
    c2, created2 = await svc.submit_candidate("workorder", "ord-1", "t", "正文")
    assert created1 is True and created2 is False
    assert c1.candidate_id == c2.candidate_id


async def test_graph_replace_and_meta(pg_repos):
    from libs.schemas.graph import EntityType, GraphCommunity, GraphEdge, GraphNode

    repo = pg_repos.graph_repo
    nodes = {
        "W-3": GraphNode(name="W-3", entity_type=EntityType.WELL, degree=1),
        "供液不足": GraphNode(name="供液不足", entity_type=EntityType.RISK, degree=1),
    }
    edges = [GraphEdge(source="W-3", target="供液不足", relation="存在风险", weight=2.0)]
    communities = {"com-1": GraphCommunity(community_id="com-1", title="W-3 社区",
                                           members=["W-3"], size=1)}
    await repo.replace_graph(nodes, edges, communities)

    assert await repo.count() == 2
    assert (await repo.get_node("W-3")).entity_type is EntityType.WELL  # type: ignore[union-attr]
    assert len(await repo.edges_of("供液不足")) == 1
    assert (await repo.list_communities())[0].community_id == "com-1"

    meta = await repo.set_meta(lambda m: setattr(m, "version", m.version + 1))
    assert meta.version == 1
    assert (await repo.get_meta()).version == 1

    # 替换语义：整图原子覆盖
    await repo.replace_graph({}, [], {})
    assert await repo.count() == 0


async def test_trace_query(pg_repos):
    from libs.schemas.trace import TraceRecord

    repo = pg_repos.trace_repo
    rec = TraceRecord(trace_id="tr-1", session_id="s-1", question="q",
                      intent="查询", duration_ms=5,
                      created_at=datetime.now(timezone.utc))
    await repo.save(rec)
    assert (await repo.get("tr-1")).session_id == "s-1"  # type: ignore[union-attr]
    assert len(await repo.query(session_id="s-1", intent="查询")) == 1
    assert await repo.query(session_id="other") == []
