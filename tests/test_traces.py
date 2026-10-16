"""阶段 4：链路追踪查询 API 测试（列表过滤/分页、详情结构化、统一错误体）。"""

from fastapi.testclient import TestClient

from apps.gateway.main import create_app


def test_traces_list_after_chat():
    """对话后 trace 落库：列表倒序、摘要视图含 result_count。"""
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat", json={"message": "3号井今天的井口日产量是多少？"})
        assert r.status_code == 200
        trace_id = r.json()["trace_id"]

        r2 = client.get("/api/v1/traces")
        assert r2.status_code == 200
        body = r2.json()
        assert body["total"] >= 1
        assert body["items"][0]["trace_id"] == trace_id  # 按创建时间倒序
        item = body["items"][0]
        assert {"trace_id", "session_id", "question", "intent", "need_clarify",
                "agents", "conflicts", "partial", "duration_ms", "created_at",
                "result_count"} <= item.keys()
        assert item["result_count"] >= 1
        assert "results" not in item  # 列表不携带全量载荷


def test_traces_filter_by_session_and_intent():
    """会话与意图过滤：session_id 精确匹配；澄清与查询意图可区分。"""
    with TestClient(create_app()) as client:
        client.post("/api/v1/chat", json={
            "message": "3号井今天的井口日产量是多少？", "session_id": "sess-t1"})
        client.post("/api/v1/chat", json={
            "message": "3号井今天的产量是多少？", "session_id": "sess-t2"})

        r = client.get("/api/v1/traces", params={"session_id": "sess-t1"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert all(t["session_id"] == "sess-t1" for t in body["items"])
        assert body["items"][0]["need_clarify"] is False

        r2 = client.get("/api/v1/traces", params={"session_id": "sess-t2"})
        assert r2.json()["items"][0]["need_clarify"] is True
        assert r2.json()["items"][0]["result_count"] == 0  # 澄清路径无节点结论

        # 意图过滤：生产查询
        r3 = client.get("/api/v1/traces", params={"intent": "production_query"})
        assert r3.status_code == 200
        assert r3.json()["total"] >= 1
        assert all(t["intent"] == "production_query" for t in r3.json()["items"])

        # 无匹配会话
        r4 = client.get("/api/v1/traces", params={"session_id": "sess-none"})
        assert r4.status_code == 200
        assert r4.json()["total"] == 0
        assert r4.json()["items"] == []


def test_trace_detail_structured_results():
    """详情返回全量节点结论：evidence/citations/data 结构化可回溯。"""
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat", json={"message": "3号井今天的井口日产量是多少？"})
        trace_id = r.json()["trace_id"]

        r2 = client.get(f"/api/v1/traces/{trace_id}")
        assert r2.status_code == 200
        record = r2.json()
        assert record["trace_id"] == trace_id
        assert record["question"] == "3号井今天的井口日产量是多少？"
        assert record["results"]
        dc = next(v for v in record["results"] if v["agent"] == "data_collector")
        assert {"agent", "trace_id", "conclusion", "confidence", "evidence",
                "suggestion", "parameter_advice", "data", "citations",
                "confidence_level", "needs_review", "partial"} <= dc.keys()
        assert dc["evidence"]


def test_trace_api_404_and_validation():
    """不存在 404；时间窗非法 400——统一错误体。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/traces/tr-不存在")
        assert r.status_code == 404
        error = r.json()["error"]
        assert error["code"] == "NOT_FOUND"
        assert error["request_id"]

        r2 = client.get("/api/v1/traces", params={
            "start": "2026-10-16T12:00:00", "end": "2026-10-16T08:00:00"})
        assert r2.status_code == 400
        assert r2.json()["error"]["code"] == "BAD_REQUEST"

        r3 = client.get("/api/v1/traces", params={"start": "not-a-date"})
        assert r3.status_code == 400
        assert r3.json()["error"]["code"] == "BAD_REQUEST"

        r4 = client.get("/api/v1/traces", params={
            "start": "2026-01-01T00:00:00", "end": "2026-12-31T00:00:00"})
        assert r4.status_code == 400  # 跨度 > 31 天


def test_traces_time_window_filter():
    """时间窗过滤：窗口内命中，窗口外为空。"""
    from datetime import datetime, timedelta, timezone

    with TestClient(create_app()) as client:
        client.post("/api/v1/chat", json={"message": "3号井今天的井口日产量是多少？"})
        now = datetime.now(timezone.utc)

        r = client.get("/api/v1/traces", params={
            "start": (now - timedelta(minutes=5)).isoformat()})
        assert r.status_code == 200
        assert r.json()["total"] >= 1

        r2 = client.get("/api/v1/traces", params={
            "start": (now - timedelta(days=2)).isoformat(),
            "end": (now - timedelta(days=1)).isoformat()})
        assert r2.status_code == 200
        assert r2.json()["total"] == 0
