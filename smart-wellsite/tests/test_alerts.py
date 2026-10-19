"""阶段 3：告警 + 工单闭环测试（服务层状态机 / 去重升级 / 超时升级 / API）。"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from apps.gateway.main import create_app
from libs.api.errors import ConflictError, NotFoundError
from libs.schemas import Level
from libs.schemas.alerts import AlertStatus, WorkOrderStatus
from repositories.alert_repo import AlertRepository, WorkOrderRepository
from services.alert_service import AlertService

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def _service() -> AlertService:
    return AlertService(AlertRepository(), WorkOrderRepository())


# ---------------- 服务层：接入与去重 ----------------

@pytest.mark.asyncio
async def test_ingest_warning_creates_alert_and_workorder():
    svc = _service()
    alert, created = await svc.ingest("env_monitor", "H2S 超阈值",
                                      Level.WARNING.value, "W-7", now=NOW)
    assert created is True
    assert alert.status is AlertStatus.ACTIVE
    assert alert.hit_count == 1

    orders = await svc._orders.query()
    assert len(orders) == 1
    assert orders[0].alert_id == alert.alert_id
    assert orders[0].priority == Level.WARNING.value
    assert orders[0].well_id == "W-7"


@pytest.mark.asyncio
async def test_ingest_info_level_skips_workorder():
    svc = _service()
    await svc.ingest("env_monitor", "气象提示", Level.INFO.value, now=NOW)
    assert await svc._orders.count() == 0


@pytest.mark.asyncio
async def test_dedup_aggregates_same_source_cause_within_window():
    svc = _service()
    a1, _ = await svc.ingest("video", "未戴安全帽", Level.WARNING.value, "CAM-03", now=NOW)
    a2, created2 = await svc.ingest("video", "未戴安全帽", Level.WARNING.value,
                                    "CAM-03", now=NOW + timedelta(minutes=3))
    assert created2 is False
    assert a2.alert_id == a1.alert_id
    assert a2.hit_count == 2
    assert a2.suppressed_count == 1
    assert await svc._alerts.count() == 1
    # 滑动窗口外再发生 → 新告警（距上次命中 > 10 分钟）
    a3, created3 = await svc.ingest("video", "未戴安全帽", Level.WARNING.value,
                                    "CAM-03", now=NOW + timedelta(minutes=14))
    assert created3 is True
    assert a3.alert_id != a1.alert_id


@pytest.mark.asyncio
async def test_dedup_level_escalation_updates_alert_level():
    svc = _service()
    await svc.ingest("env_monitor", "H2S 超阈值", Level.WARNING.value, "W-7", now=NOW)
    alert, created = await svc.ingest("env_monitor", "H2S 超阈值",
                                      Level.CRITICAL.value, "W-7",
                                      now=NOW + timedelta(minutes=2))
    assert created is False
    assert alert.level == Level.CRITICAL.value
    assert len(alert.escalations) == 1
    assert alert.escalations[0].kind == "dedup"
    assert alert.escalations[0].from_level == Level.WARNING.value


# ---------------- 服务层：状态机 ----------------

@pytest.mark.asyncio
async def test_alert_state_machine_rejects_illegal_transitions():
    svc = _service()
    alert, _ = await svc.ingest("env_monitor", "H2S 超阈值",
                                Level.WARNING.value, "W-7", now=NOW)

    acked = await svc.acknowledge(alert.alert_id, "值班员A")
    assert acked.status is AlertStatus.ACKNOWLEDGED
    assert acked.acknowledged_by == "值班员A"

    with pytest.raises(ConflictError):
        await svc.acknowledge(alert.alert_id, "值班员A")  # 重复确认

    resolved = await svc.resolve(alert.alert_id, "值班员A", "现场已处置")
    assert resolved.status is AlertStatus.RESOLVED
    assert resolved.resolution == "现场已处置"

    with pytest.raises(ConflictError):
        await svc.resolve(alert.alert_id, "值班员A", "重复关闭")

    with pytest.raises(NotFoundError):
        await svc.acknowledge("alt-不存在", "值班员A")


@pytest.mark.asyncio
async def test_workorder_full_lifecycle_and_illegal_skips():
    svc = _service()
    alert, _ = await svc.ingest("env_monitor", "H2S 超阈值",
                                Level.CRITICAL.value, "W-7", now=NOW)
    order = (await svc._orders.query())[0]

    with pytest.raises(ConflictError):
        await svc.close_order(order.order_id, "班长", "直接关闭")  # pending 不可关闭

    processing = await svc.assign_order(order.order_id, "维修工B", "值班员A")
    assert processing.status is WorkOrderStatus.PROCESSING
    assert processing.assignee == "维修工B"

    resolved = await svc.resolve_order(order.order_id, "维修工B", "已紧固阀门")
    assert resolved.status is WorkOrderStatus.RESOLVED
    assert resolved.resolved_at is not None

    closed = await svc.close_order(order.order_id, "班长", "法兰垫片老化")
    assert closed.status is WorkOrderStatus.CLOSED
    assert closed.actual_cause == "法兰垫片老化"
    assert closed.alert_id == alert.alert_id


# ---------------- 服务层：超时升级 ----------------

@pytest.mark.asyncio
async def test_sweep_escalates_unacked_critical_alert():
    svc = _service()
    await svc.ingest("env_monitor", "H2S 超阈值", Level.CRITICAL.value, "W-7", now=NOW)
    result = await svc.sweep_timeouts(now=NOW + timedelta(minutes=6))
    assert result["alerts_escalated"] == 1

    alert = (await svc._alerts.query())[0]
    assert alert.escalations[0].kind == "timeout"
    assert "值班班长" in alert.escalations[0].notified
    # 已重置窗口：紧接着再扫不重复升级
    result2 = await svc.sweep_timeouts(now=NOW + timedelta(minutes=7))
    assert result2["alerts_escalated"] == 0


@pytest.mark.asyncio
async def test_sweep_escalates_warning_to_critical_and_order_timeout():
    svc = _service()
    await svc.ingest("env_monitor", "H2S 超阈值", Level.WARNING.value, "W-7", now=NOW)
    result = await svc.sweep_timeouts(now=NOW + timedelta(minutes=31))
    assert result["alerts_escalated"] == 1

    alert = (await svc._alerts.query())[0]
    assert alert.level == Level.CRITICAL.value  # 预警 → 紧急

    # 工单 1 小时未接单 → 督办升级
    result2 = await svc.sweep_timeouts(now=NOW + timedelta(hours=1, minutes=1))
    assert result2["orders_escalated"] == 1
    order = (await svc._orders.query())[0]
    assert order.escalations[0].kind == "timeout"


@pytest.mark.asyncio
async def test_sweep_ignores_acknowledged_alerts():
    svc = _service()
    alert, _ = await svc.ingest("env_monitor", "H2S 超阈值",
                                Level.CRITICAL.value, "W-7", now=NOW)
    await svc.acknowledge(alert.alert_id, "值班员A")
    result = await svc.sweep_timeouts(now=NOW + timedelta(minutes=10))
    assert result["alerts_escalated"] == 0


# ---------------- API 层 ----------------

def _ask_h2s(client: TestClient) -> None:
    r = client.post("/api/v1/chat", json={"message": "W-7 井口有没有硫化氢风险？"})
    assert r.status_code == 200


def test_alert_api_full_flow():
    """对话链路派生告警 → 列表/详情 → 确认 → 关闭；工单同步生成并走完全流程。"""
    with TestClient(create_app()) as client:
        _ask_h2s(client)

        r = client.get("/api/v1/alerts")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        alert = body["items"][0]
        assert alert["status"] == "active"
        assert alert["source"] in ("env_monitor", "safety_risk", "video_intelligence")

        alert_id = alert["alert_id"]
        r_detail = client.get(f"/api/v1/alerts/{alert_id}")
        assert r_detail.status_code == 200

        # 确认 → 关闭
        r_ack = client.post(f"/api/v1/alerts/{alert_id}/acknowledge",
                            json={"operator": "值班员A"})
        assert r_ack.status_code == 200
        assert r_ack.json()["status"] == "acknowledged"

        r_ack2 = client.post(f"/api/v1/alerts/{alert_id}/acknowledge",
                             json={"operator": "值班员A"})
        assert r_ack2.status_code == 409
        assert r_ack2.json()["error"]["code"] == "CONFLICT"

        r_res = client.post(f"/api/v1/alerts/{alert_id}/resolve",
                            json={"operator": "值班员A", "resolution": "已处置"})
        assert r_res.status_code == 200
        assert r_res.json()["status"] == "resolved"

        # 状态过滤
        r_active = client.get("/api/v1/alerts", params={"status": "active"})
        assert all(a["status"] == "active" for a in r_active.json()["items"])

        # 工单（预警/紧急告警已自动生成）
        r_orders = client.get("/api/v1/workorders")
        assert r_orders.status_code == 200
        if r_orders.json()["total"] >= 1:
            order = r_orders.json()["items"][0]
            oid = order["order_id"]
            assert client.post(f"/workorders/{oid}/assign").status_code == 404  # 路径校验
            r_assign = client.post(f"/api/v1/workorders/{oid}/assign",
                                   json={"operator": "值班员A", "assignee": "维修工B"})
            assert r_assign.status_code == 200
            assert r_assign.json()["status"] == "processing"

            r_resolve = client.post(f"/api/v1/workorders/{oid}/resolve",
                                    json={"operator": "维修工B", "resolution": "已修复"})
            assert r_resolve.json()["status"] == "resolved"

            r_close = client.post(f"/api/v1/workorders/{oid}/close",
                                  json={"operator": "班长", "actual_cause": "密封圈老化"})
            assert r_close.json()["status"] == "closed"


def test_alert_api_404_and_validation():
    """不存在资源 404；参数缺失 422；等级非法 400——全部统一错误体。"""
    with TestClient(create_app()) as client:
        r = client.get("/api/v1/alerts/alt-不存在")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

        r2 = client.post("/api/v1/alerts/alt-不存在/acknowledge",
                         json={"operator": "值班员A"})
        assert r2.status_code == 404

        r3 = client.post("/api/v1/alerts/alt-x/acknowledge", json={})
        assert r3.status_code == 422
        assert r3.json()["error"]["code"] == "VALIDATION_ERROR"

        r4 = client.get("/api/v1/alerts", params={"level": "严重"})
        assert r4.status_code == 400
        assert r4.json()["error"]["code"] == "BAD_REQUEST"

        r5 = client.get("/api/v1/workorders/ord-不存在")
        assert r5.status_code == 404
