"""Gateway healthz 和 chat 测试。"""

import pytest
from httpx import AsyncClient, ASGITransport

from apps.gateway.main import app


@pytest.mark.asyncio
async def test_healthz():
    """健康检查应返回 200 + ok。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.1.0"


@pytest.mark.asyncio
async def test_chat_endpoint():
    """对话接口应返回 Mock 响应。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/chat",
            json={"message": "3号井有什么故障？"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert data["session_id"]
    assert len(data["reply"]) > 0


@pytest.mark.asyncio
async def test_metrics_endpoint():
    """Prometheus 指标端点应返回文本。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert "wellsite_gateway_requests_total" in resp.text
