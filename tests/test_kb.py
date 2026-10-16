"""阶段 5：知识库管理测试（分块/索引状态机/检索/删除级联/API）。"""

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from libs.api.errors import NotFoundError
from libs.schemas.kb import IndexStatus
from repositories.kb_repo import KBChunkRepository, KBDocumentRepository
from services.kb_service import KBService, chunk_text, extract_tags


def _service() -> tuple[KBService, KBDocumentRepository, KBChunkRepository]:
    docs, chunks = KBDocumentRepository(), KBChunkRepository()
    return KBService(docs, chunks), docs, chunks


# ---------------- 服务层：分块与 tag 抽取 ----------------

def test_chunk_text_paragraph_and_sentence_split():
    short = "短段落。"
    assert chunk_text(short) == ["短段落。"]

    long_para = "第一句。" * 100  # 500 字单段，按句子切
    blocks = chunk_text(long_para, max_chars=300)
    assert len(blocks) >= 2
    assert all(len(b) <= 300 for b in blocks)
    assert "".join(blocks).replace("\n", "") == long_para

    multi = "段落一内容。\n\n段落二内容。"
    assert chunk_text(multi) == ["段落一内容。\n段落二内容。"]  # 短相邻块合并


def test_extract_tags_domain_keywords_and_extra():
    tags = extract_tags("W-3 泵效下降、沉没度下降，应调低冲次", ["自定义"])
    assert "泵效" in tags and "沉没度" in tags and "冲次" in tags
    assert "自定义" in tags
    assert len(tags) == len(set(tags))  # 去重


# ---------------- 服务层：索引状态机 ----------------

@pytest.mark.asyncio
async def test_create_and_index_document_sync():
    svc, docs, chunks = _service()
    doc = await svc.create_document(
        title="H2S 检测规程", doc_type="规程", source_ref="《检测规程》1.1",
        text="H2S 浓度超过 10ppm 时应佩戴检测仪接近确认。",
        tags=["H2S"], background=False,
    )
    ready = await docs.get_by_id(doc.doc_id)
    assert ready.status is IndexStatus.READY
    assert ready.chunk_count == 1

    doc_chunks = await chunks.list_by_doc(doc.doc_id)
    assert len(doc_chunks) == 1
    assert "H2S" in doc_chunks[0].tags


@pytest.mark.asyncio
async def test_reindex_is_idempotent_and_clears_old_chunks():
    svc, docs, chunks = _service()
    doc = await svc.create_document(
        title="测试文档", doc_type="其他", source_ref="T-1",
        text="内容甲。\n\n内容乙。", background=False,
    )
    first = await chunks.list_by_doc(doc.doc_id)
    await svc.reindex(doc.doc_id)
    second = await chunks.list_by_doc(doc.doc_id)
    assert len(second) == len(first)
    assert {c.chunk_id for c in second} != {c.chunk_id for c in first}  # 全新分块

    with pytest.raises(NotFoundError):
        await svc.reindex("kb-不存在")


@pytest.mark.asyncio
async def test_search_hits_only_ready_docs_and_scoring():
    svc, docs, chunks = _service()
    await svc.seed_defaults()  # 5 条种子均为 READY

    hits = await svc.search("H2S 泄漏怎么处置", top_k=3)
    assert hits
    assert hits[0]["type"] == "预案"
    assert hits[0]["score"] >= hits[-1]["score"]
    assert {"id", "chunk_id", "source_ref", "type", "title", "text",
            "tags", "score"} <= hits[0].keys()

    # 类型过滤
    cases = await svc.search("供液不足 泵效", top_k=3, doc_type="案例")
    assert cases and all(h["type"] == "案例" for h in cases)

    # 未命中返回空
    assert await svc.search("量子计算机维护") == []


@pytest.mark.asyncio
async def test_delete_document_cascades_chunks():
    svc, docs, chunks = _service()
    doc = await svc.create_document(
        title="待删除", doc_type="其他", source_ref="D-1",
        text="内容", background=False,
    )
    await svc.delete_document(doc.doc_id)
    assert await docs.get_by_id(doc.doc_id) is None
    assert await chunks.list_by_doc(doc.doc_id) == []

    with pytest.raises(NotFoundError):
        await svc.delete_document(doc.doc_id)


# ---------------- API 层 ----------------

def _wait_ready(client: TestClient, doc_id: str, retries: int = 30) -> dict:
    import time

    for _ in range(retries):
        body = client.get(f"/api/v1/kb/documents/{doc_id}").json()
        if body["document"]["status"] == "ready":
            return body
        time.sleep(0.02)
    raise AssertionError(f"文档 {doc_id} 索引超时")


def test_kb_api_seeded_and_full_crud_flow():
    """种子 5 条 READY；上传→轮询 READY→检索命中→详情含 chunk→删除后不可检索。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/kb/documents")
        assert r.status_code == 200
        assert r.json()["total"] == 5
        assert all(d["status"] == "ready" for d in r.json()["items"])
        assert {"doc_id", "title", "doc_type", "source_ref", "summary",
                "tags", "status", "chunk_count"} <= r.json()["items"][0].keys()

        # 上传（后台索引）
        r2 = client.post("/api/v1/kb/documents", json={
            "title": "安全帽佩戴规定", "doc_type": "规程",
            "source_ref": "《井场安全规定》第 1 章",
            "text": "进入生产区必须佩戴安全帽，视频识别未佩戴立即告警。",
            "tags": ["安全帽"],
        })
        assert r2.status_code == 201
        doc_id = r2.json()["doc_id"]
        assert r2.json()["status"] in ("pending", "indexing", "ready")

        detail = _wait_ready(client, doc_id)
        assert detail["document"]["chunk_count"] == 1
        assert detail["chunks"][0]["tags"]
        assert "安全帽" in detail["chunks"][0]["tags"]

        # 检索测试
        r3 = client.post("/api/v1/kb/search", json={"query": "未戴安全帽告警"})
        assert r3.status_code == 200
        assert any(h["id"] == doc_id for h in r3.json())

        # 删除 → 204，检索不再命中
        r4 = client.delete(f"/api/v1/kb/documents/{doc_id}")
        assert r4.status_code == 204
        assert client.get(f"/api/v1/kb/documents/{doc_id}").status_code == 404
        r5 = client.post("/api/v1/kb/search", json={"query": "未戴安全帽告警"})
        assert all(h["id"] != doc_id for h in r5.json())


def test_kb_api_validation_and_404():
    """非法参数 422；不存在资源 404——统一错误体。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/kb/documents/kb-不存在")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

        r2 = client.post("/api/v1/kb/documents", json={
            "title": "", "source_ref": "x", "text": "y"})
        assert r2.status_code == 422
        assert r2.json()["error"]["code"] == "VALIDATION_ERROR"

        r3 = client.post("/api/v1/kb/search", json={"query": "  "})
        assert r3.status_code == 200  # 空白 query 由服务层返回空命中
        assert r3.json() == []

        r4 = client.post("/api/v1/kb/search", json={"query": ""})
        assert r4.status_code == 422

        r5 = client.post("/api/v1/kb/documents/kb-不存在/reindex")
        assert r5.status_code == 404

        r6 = client.delete("/api/v1/kb/documents/kb-不存在")
        assert r6.status_code == 404


def test_kb_api_search_type_filter_and_agent_uses_service():
    """检索类型过滤；对话链路的知识问答走统一 KBService（种子可命中）。"""
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/kb/search",
                        json={"query": "供液不足 泵效 冲次", "doc_type": "案例"})
        assert r.status_code == 200
        assert all(h["type"] == "案例" for h in r.json())

        # 对话链路：H2S 处置问答应命中种子预案并附 source_refs
        r2 = client.post("/api/v1/chat",
                         json={"message": "硫化氢泄漏应该怎么应急处置？"})
        assert r2.status_code == 200
        views = {v["agent"]: v for v in r2.json()["results"]}
        if "report_knowledge" in views:
            rk = views["report_knowledge"]
            assert rk["citations"]
            assert any("预案" in c or "硫化氢" in c for c in rk["citations"])
