"""API 层测试：健康检查与对话入口（含编排链路）。"""

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
