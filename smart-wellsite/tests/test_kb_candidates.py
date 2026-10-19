"""候选沉淀管道测试（自进化：工单闭环/高频告警/trace 沉淀 → 审核 → 入库）。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from libs.api.errors import ConflictError, NotFoundError
from libs.schemas import Level
from libs.schemas.kb import CandidateStatus, IndexStatus
from repositories.alert_repo import AlertRepository, WorkOrderRepository
from repositories.kb_repo import (
    KBCandidateRepository,
    KBChunkRepository,
    KBDocumentRepository,
)
from services.alert_service import AlertService
from services.kb_service import KBService

NOW = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)


def _stack():
    docs, chunks, cands = (KBDocumentRepository(), KBChunkRepository(),
                           KBCandidateRepository())
    kb = KBService(docs, chunks, cands)
    alerts, orders = AlertRepository(), WorkOrderRepository()
    svc = AlertService(alerts, orders)
    svc.set_kb_service(kb)
    return svc, kb, cands, docs


# ---------------- 服务层：沉淀钩子 ----------------

@pytest.mark.asyncio
async def test_closed_order_distills_case_candidate():
    svc, kb, cands, docs = _stack()
    await svc.ingest("env_monitor", "H2S 超阈值", Level.CRITICAL.value,
                     "W-7", now=NOW)
    order = (await svc._orders.query())[0]
    await svc.assign_order(order.order_id, "维修工B", "值班员A")
    await svc.resolve_order(order.order_id, "维修工B", "已更换密封圈")
    await svc.close_order(order.order_id, "班长", "密封圈老化")

    items = await cands.query(status=CandidateStatus.PENDING)
    assert len(items) == 1
    cand = items[0]
    assert cand.source_type == "workorder"
    assert cand.source_id == order.order_id
    assert "W-7" in cand.title
    assert "密封圈老化" in cand.text
    assert cand.doc_type == "案例"


@pytest.mark.asyncio
async def test_frequent_alert_distills_risk_candidate_idempotent():
    svc, kb, cands, docs = _stack()
    for i in range(4):  # 滑动窗口内同源同因 4 次
        await svc.ingest("video", "未戴安全帽", Level.WARNING.value,
                         "CAM-03", now=NOW + timedelta(minutes=i))
    items = await cands.query()
    assert len(items) == 1  # 幂等：第 3、4 次命中只生成一次
    cand = items[0]
    assert cand.source_type == "alert_dedup"
    assert "未戴安全帽" in cand.title
    assert "4 次" in cand.text or "3 次" in cand.text


@pytest.mark.asyncio
async def test_submit_candidate_idempotent_by_source():
    svc, kb, cands, docs = _stack()
    c1, created1 = await kb.submit_candidate("trace", "tr-1", "标题", "正文")
    c2, created2 = await kb.submit_candidate("trace", "tr-1", "标题", "正文")
    assert created1 is True and created2 is False
    assert c1.candidate_id == c2.candidate_id
    assert await cands.count() == 1


@pytest.mark.asyncio
async def test_approve_reject_state_machine():
    svc, kb, cands, docs = _stack()
    cand, _ = await kb.submit_candidate("trace", "tr-2", "供液不足案例",
                                        "W-3 泵效下降，调低冲次。")

    approved, doc = await kb.approve_candidate(
        cand.candidate_id, "工艺员C",
        overrides={"title": "W-3 供液不足调参案例"})
    assert approved.status is CandidateStatus.APPROVED
    assert approved.doc_id == doc.doc_id
    assert approved.reviewed_by == "工艺员C"
    assert doc.title == "W-3 供液不足调参案例"
    assert doc.status is IndexStatus.READY  # 同步索引即可检索
    hits = await kb.search("供液不足 冲次")
    assert any(h["id"] == doc.doc_id for h in hits)

    with pytest.raises(ConflictError):
        await kb.approve_candidate(cand.candidate_id, "工艺员C")
    with pytest.raises(ConflictError):
        await kb.reject_candidate(cand.candidate_id, "工艺员C", "已采纳")

    cand2, _ = await kb.submit_candidate("trace", "tr-3", "低质候选", "内容")
    rejected = await kb.reject_candidate(cand2.candidate_id, "工艺员C", "内容不准")
    assert rejected.status is CandidateStatus.REJECTED
    assert rejected.review_note == "内容不准"
    assert await docs.count() == 1  # 驳回不入库

    with pytest.raises(NotFoundError):
        await kb.approve_candidate("cand-不存在", "工艺员C")


# ---------------- API 层 ----------------

def _close_one_order(client: TestClient) -> None:
    """触发 H2S 告警并走完工单闭环。"""
    client.post("/api/v1/chat", json={"message": "W-7 井口有没有硫化氢风险？"})
    orders = client.get("/api/v1/workorders").json()["items"]
    if not orders:
        return
    oid = orders[0]["order_id"]
    client.post(f"/api/v1/workorders/{oid}/assign",
                json={"operator": "值班员A", "assignee": "维修工B"})
    client.post(f"/api/v1/workorders/{oid}/resolve",
                json={"operator": "维修工B", "resolution": "已紧固阀门"})
    client.post(f"/api/v1/workorders/{oid}/close",
                json={"operator": "班长", "actual_cause": "法兰垫片老化"})


def test_candidate_full_lifecycle_via_api():
    """工单闭环自动沉淀 → 队列查询 → 采纳入库（可检索 + 图谱重建）→ 终态 409。"""
    import time

    with TestClient(create_app()) as client:
        _close_one_order(client)

        r = client.get("/api/v1/kb/candidates", params={"status": "pending"})
        assert r.status_code == 200
        assert r.json()["total"] >= 1
        cand = r.json()["items"][0]
        assert cand["source_type"] == "workorder"
        assert {"candidate_id", "source_type", "source_id", "title",
                "doc_type", "text", "tags", "status"} <= cand.keys()

        # 检索前：候选内容未入库
        r_pre = client.post("/api/v1/kb/search",
                            json={"query": "法兰垫片老化"})
        assert all("法兰垫片" not in h["text"] for h in r_pre.json())

        # 采纳（编辑标题）
        cid = cand["candidate_id"]
        r2 = client.post(f"/api/v1/kb/candidates/{cid}/approve",
                         json={"reviewer": "工艺员C",
                               "title": "W-7 法兰泄漏处置案例"})
        assert r2.status_code == 200
        body = r2.json()
        assert body["candidate"]["status"] == "approved"
        assert body["document"]["status"] == "ready"
        assert body["graph_rebuild"] == "triggered"

        # 入库后即可检索
        r3 = client.post("/api/v1/kb/search", json={"query": "法兰垫片老化"})
        assert any("法兰垫片" in h["text"] for h in r3.json())

        # 图谱重建被触发（轮询至 done）
        for _ in range(50):
            meta = client.get("/api/v1/graph/rebuild/status").json()
            if meta["status"] == "done":
                break
            time.sleep(0.02)
        assert meta["version"] >= 2

        # 终态重复审核 → 409
        r4 = client.post(f"/api/v1/kb/candidates/{cid}/approve",
                         json={"reviewer": "工艺员C"})
        assert r4.status_code == 409
        assert r4.json()["error"]["code"] == "CONFLICT"


def test_candidate_distill_trace_and_validation():
    """trace 手动沉淀（幂等）；404/400/422 统一错误体。"""
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat",
                        json={"message": "3号井今天的井口日产量是多少？"})
        trace_id = r.json()["trace_id"]

        r2 = client.post("/api/v1/kb/candidates/distill",
                         json={"trace_id": trace_id})
        assert r2.status_code == 201
        cand = r2.json()
        assert cand["source_type"] == "trace"
        assert "3号井" in cand["text"]

        # 幂等：重复沉淀返回同一候选
        r3 = client.post("/api/v1/kb/candidates/distill",
                         json={"trace_id": trace_id})
        assert r3.json()["candidate_id"] == cand["candidate_id"]

        # 不存在 trace → 404
        r4 = client.post("/api/v1/kb/candidates/distill",
                         json={"trace_id": "tr-不存在"})
        assert r4.status_code == 404

        # 澄清路径（无节点结论）→ 400
        r5 = client.post("/api/v1/chat", json={"message": "3号井今天的产量是多少？"})
        clarify_trace = r5.json()["trace_id"]
        r6 = client.post("/api/v1/kb/candidates/distill",
                         json={"trace_id": clarify_trace})
        assert r6.status_code == 400
        assert r6.json()["error"]["code"] == "BAD_REQUEST"

        # 缺 reviewer → 422；不存在候选 → 404
        r7 = client.post(f"/api/v1/kb/candidates/{cand['candidate_id']}/approve",
                         json={})
        assert r7.status_code == 422
        r8 = client.post("/api/v1/kb/candidates/cand-不存在/reject",
                         json={"reviewer": "工艺员C", "review_note": "x"})
        assert r8.status_code == 404

        # 驳回 → 终态
        r9 = client.post(f"/api/v1/kb/candidates/{cand['candidate_id']}/reject",
                         json={"reviewer": "工艺员C", "review_note": "问答过于简单"})
        assert r9.status_code == 200
        assert r9.json()["status"] == "rejected"
