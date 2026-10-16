"""API 层测试：健康检查与对话入口（含编排链路）。"""

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import create_app


def test_healthz_reports_orchestrator_ready():
    with TestClient(create_app()) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["services"]["orchestrator"] == "ready"
        assert body["services"]["agents"] == "10"


def test_chat_runs_full_pipeline():
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat", json={"message": "3号井今天的井口日产量是多少？"})
        assert r.status_code == 200
        body = r.json()
        assert body["reply"]
        assert body["trace_id"].startswith("tr-")
        assert "data_collector" in body["tools_called"]
        assert "production_analysis" in body["tools_called"]
        assert body["citations"]
        assert body["results"]


def test_chat_clarify_path():
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat", json={"message": "3号井今天的产量是多少？"})
        assert r.status_code == 200
        body = r.json()
        assert body["need_clarify"] is True
        assert body["clarify_options"]
        assert body["tools_called"] == []


def test_metrics_endpoint():
    with TestClient(create_app()) as client:
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "wellsite_gateway_requests_total" in r.text


# ---------------- 阶段 1：生产级骨架 ----------------

def test_request_id_echo_generated_and_sanitized():
    """X-Request-ID 透传 / 缺失生成 / 非法字符清洗防注入。"""
    with TestClient(create_app()) as client:
        r = client.get("/healthz", headers={"X-Request-ID": "req-abc-123"})
        assert r.headers["x-request-id"] == "req-abc-123"

        r2 = client.get("/healthz")
        generated = r2.headers["x-request-id"]
        assert generated and len(generated) >= 16

        r3 = client.get("/healthz", headers={"X-Request-ID": "bad id\r\nX-Evil: 1"})
        rid = r3.headers["x-request-id"]
        assert all(ch.isalnum() or ch in "-_" for ch in rid)


def test_blank_message_returns_unified_validation_error():
    """空白消息 → 422 统一错误体。"""
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat", json={"message": "   "})
        assert r.status_code == 422
        error = r.json()["error"]
        assert error["code"] == "VALIDATION_ERROR"
        assert error["request_id"]
        assert error["details"]


def test_unknown_route_returns_unified_error_envelope():
    """未知路由 → 404 统一错误体。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/does-not-exist")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"


def test_chat_result_views_expose_evidence_and_payload():
    """节点结论视图必须带 evidence/suggestion/parameter_advice/data/citations。"""
    with TestClient(create_app()) as client:
        r = client.post("/api/v1/chat", json={"message": "3号井今天的井口日产量是多少？"})
        assert r.status_code == 200
        views = {v["agent"]: v for v in r.json()["results"]}

        required = {"evidence", "suggestion", "parameter_advice", "data", "citations",
                    "confidence_level", "needs_review", "partial"}
        assert required.issubset(views["data_collector"].keys())
        assert views["production_analysis"]["evidence"]


@pytest.mark.asyncio
async def test_orchestrator_persists_full_trace():
    """编排器每次请求（含澄清路径）都全量落库 trace。"""
    from apps.orchestrator import build_orchestrator
    from libs.llm import MockLLMClient
    from repositories.trace_repo import TraceRepository
    from services.trace_recorder import TraceRecorder

    repo = TraceRepository()
    orchestrator = build_orchestrator(
        MockLLMClient(delay=0), trace_recorder=TraceRecorder(repo)
    )

    final = await orchestrator.run("3号井今天的井口日产量是多少？", "session-trace-1")
    records = await repo.query(session_id="session-trace-1")
    assert len(records) == 1
    record = records[0]
    assert record.trace_id == final.trace_id
    assert record.session_id == "session-trace-1"
    assert record.agents == [r.agent.value for r in final.results]
    assert record.results
    assert record.duration_ms >= 0

    await orchestrator.run("3号井今天的产量是多少？", "session-trace-2")
    clarify = await repo.query(session_id="session-trace-2")
    assert len(clarify) == 1
    assert clarify[0].need_clarify is True
    assert clarify[0].agents == []


@pytest.mark.asyncio
async def test_trace_query_filters_by_time_window():
    """trace 仓储时间窗口过滤与倒序返回。"""
    from datetime import datetime, timedelta, timezone

    from libs.schemas.trace import TraceRecord
    from repositories.trace_repo import TraceRepository

    repo = TraceRepository()
    now = datetime.now(timezone.utc)
    for idx in range(3):
        await repo.save(TraceRecord(
            trace_id=f"tr-t{idx}", question=f"q{idx}", intent="query",
            created_at=now - timedelta(minutes=idx),
        ))

    recent = await repo.query(start=now - timedelta(seconds=90))
    assert [r.trace_id for r in recent] == ["tr-t0", "tr-t1"]

    all_records = await repo.query()
    assert [r.trace_id for r in all_records] == ["tr-t0", "tr-t1", "tr-t2"]


# ---------------- 阶段 2：井号/时序/事件日历只读接口 ----------------

from sim.timebase import DATE, at  # noqa: E402


def test_list_wells_paginated():
    """井号台账分页：total/total_pages/items 结构正确。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/wells", params={"page_size": 3, "page": 2})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 7
        assert body["page"] == 2
        assert body["page_size"] == 3
        assert body["total_pages"] == 3
        assert len(body["items"]) == 3
        item = body["items"][0]
        assert {"well_id", "name", "well_type", "well_type_cn",
                "device_id", "device_type", "location", "status"} <= item.keys()


def test_list_wells_filter_by_type():
    """按井型过滤；非法井型返回统一 400。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/wells", params={"well_type": "gas"})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3
        assert {w["well_id"] for w in body["items"]} == {"W-2", "W-6", "W-7"}
        assert all(w["well_type_cn"] == "采气" for w in body["items"])

        r2 = client.get("/api/v1/wells", params={"well_type": "nuclear"})
        assert r2.status_code == 400
        assert r2.json()["error"]["code"] == "BAD_REQUEST"


def test_get_well_detail_and_not_found():
    """单井详情支持别名归一化；不存在返回统一 404。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/wells/W-3")
        assert r.status_code == 200
        assert r.json()["name"] == "3号采油井"

        r_alias = client.get("/api/v1/wells/w3")
        assert r_alias.status_code == 200
        assert r_alias.json()["well_id"] == "W-3"

        r404 = client.get("/api/v1/wells/W-99")
        assert r404.status_code == 404
        error = r404.json()["error"]
        assert error["code"] == "NOT_FOUND"
        assert error["request_id"]


def test_telemetry_passthrough_with_gap_and_events():
    """时序透传：W-3 今日产量含 02:00~04:00 缺口与下行趋势事件。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/telemetry", params={
            "tag": "W3.daily_oil_prod",
            "start": f"{DATE} 00:00",
            "end": f"{DATE} 23:59",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["tag"] == "W3.daily_oil_prod"
        assert body["metric"] == "井口日产量"
        assert body["unit"] == "t/d"
        assert len(body["series"]) == 21  # 24 小时 - 3 小时缺口（02/03/04 点）
        assert body["quality"]["gap"] == [f"{DATE} 02:00~{DATE} 04:00"]
        assert body["events"]
        assert body["events"][0]["type"] == "异常"


def test_telemetry_rejects_invalid_tag_and_range():
    """非法 tag / 未登记指标 / 时间范围错误均返回统一 400。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/telemetry", params={"tag": "foo.bar"})
        assert r.status_code == 400
        error = r.json()["error"]
        assert error["code"] == "BAD_REQUEST"
        assert error["request_id"]

        r2 = client.get("/api/v1/telemetry", params={"tag": "W3.unknown_metric"})
        assert r2.status_code == 400

        r3 = client.get("/api/v1/telemetry", params={
            "tag": "W3.daily_oil_prod",
            "start": f"{DATE} 12:00",
            "end": f"{DATE} 08:00",
        })
        assert r3.status_code == 400

        r4 = client.get("/api/v1/telemetry", params={
            "tag": "W3.daily_oil_prod",
            "start": "not-a-date",
        })
        assert r4.status_code == 400


def test_events_calendar_range_and_well_filter():
    """事件日历：今日窗口命中检修/停电/限产，支持井号过滤与分页结构。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/events/calendar")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 3  # W-1 检修、W-5 停电、W-7 限产（W-2 检修在昨天）
        types = {e["event_type"] for e in body["items"]}
        assert types == {"检修", "停电", "限产"}
        assert {"event_type", "wells", "start", "end", "desc"} <= body["items"][0].keys()

        r2 = client.get("/api/v1/events/calendar", params={"well_id": "W-1"})
        assert r2.status_code == 200
        assert r2.json()["total"] == 1
        assert r2.json()["items"][0]["wells"] == ["W-1"]

        yesterday = at(-1, "09:00")
        r3 = client.get("/api/v1/events/calendar",
                        params={"from": yesterday, "to": at(-1, "23:59")})
        assert r3.json()["total"] == 2  # 昨日 W-2 检修 + 跨期 W-7 限产

        r4 = client.get("/api/v1/events/calendar", params={"well_id": "W-99"})
        assert r4.status_code == 400
        assert r4.json()["error"]["code"] == "BAD_REQUEST"
