"""PostgreSQL 种子数据：告警/工单/候选 + 扩充知识文档。

仅在空库时灌入（按 count 守卫，幂等）；id 采用确定性命名（alt-seed-*），
便于演示与联调核对。时间相对启动时刻偏移，保证超时升级扫描不抖动。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog

from libs.schemas.alerts import Alert, AlertStatus, EscalationRecord, WorkOrder, WorkOrderStatus
from libs.schemas.kb import KBCandidate

logger = structlog.get_logger(__name__)


def _ago(**kwargs) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kwargs)


# ==================== 告警 / 工单 ====================
# 语义约束：预警/紧急告警自动生成工单（ORDER_LEVELS），提醒/提示不派单。

_SEED_ALERTS: list[dict] = [
    # --- 进行中 ---
    dict(alert_id="alt-seed-01", dedup_key="dk-w3-liquid", level="预警",
         source="data_collector", cause="W-3 供液不足趋势", scope="W-3",
         content="W-3 泵效/沉没度/产量自早班起持续下行，判断供液不足",
         status=AlertStatus.ACTIVE, hit_count=3, first_seen=_ago(minutes=12)),
    dict(alert_id="alt-seed-02", dedup_key="dk-w7-pressure", level="紧急",
         source="safety_risk", cause="W-7 井口压力超上限", scope="W-7",
         content="W-7 井口压力 3.6MPa 超过安全上限 3.2MPa，存在井控风险",
         status=AlertStatus.ACTIVE, hit_count=1, first_seen=_ago(minutes=3)),
    dict(alert_id="alt-seed-03", dedup_key="dk-w2-h2s", level="提醒",
         source="environment_safety", cause="W-2 H2S 浓度临近预警值", scope="W-2",
         content="W-2 周界 H2S 浓度 8ppm，临近预警值 10ppm",
         status=AlertStatus.ACKNOWLEDGED, first_seen=_ago(minutes=50)),
    dict(alert_id="alt-seed-04", dedup_key="dk-w5-current", level="提示",
         source="device_diagnosis", cause="W-5 抽油机电流波动", scope="W-5",
         content="W-5 上行电流波动幅度超过基线 15%，建议关注",
         status=AlertStatus.ACTIVE, first_seen=_ago(minutes=25)),
    dict(alert_id="alt-seed-05", dedup_key="dk-w4-mud", level="预警",
         source="data_collector", cause="W-4 泥浆密度低于设计下限", scope="W-4",
         content="W-4 泥浆密度 1.18g/cm3 低于设计下限 1.20g/cm3，警惕井涌风险",
         status=AlertStatus.ACKNOWLEDGED, first_seen=_ago(hours=2)),
    # --- 已闭环 ---
    dict(alert_id="alt-seed-06", dedup_key="dk-w1-noise", level="提醒",
         source="video_intelligence", cause="W-1 抽油机异响", scope="W-1",
         content="W-1 现场巡检报抽油机曲柄销异响",
         status=AlertStatus.RESOLVED, first_seen=_ago(hours=3),
         resolved=("值班员", "现场紧固曲柄销螺栓，异响消除")),
    dict(alert_id="alt-seed-07", dedup_key="dk-w6-temp", level="提示",
         source="data_collector", cause="W-6 井口温度异常升高", scope="W-6",
         content="W-6 井口温度 31℃ 高于历史同期 6℃",
         status=AlertStatus.RESOLVED, first_seen=_ago(hours=5),
         resolved=("值班员", "核对为日照直射表计所致，已加装遮阳罩")),
    dict(alert_id="alt-seed-08", dedup_key="dk-w2-throttle", level="预警",
         source="device_diagnosis", cause="W-2 节流前压力持续升高", scope="W-2",
         content="W-2 节流前压力 2 小时内由 3.1MPa 升至 3.8MPa，疑似冰堵",
         status=AlertStatus.RESOLVED, first_seen=_ago(hours=6),
         resolved=("张工", "热洗节流阀后压力回落至 3.0MPa")),
    dict(alert_id="alt-seed-09", dedup_key="dk-w3-pumpeff", level="预警",
         source="device_diagnosis", cause="W-3 泵效低于阈限", scope="W-3",
         content="W-3 泵效 0.30 低于阈限 0.35",
         status=AlertStatus.RESOLVED, first_seen=_ago(hours=26),
         resolved=("李工", "冲次由 6 次/min 调至 4 次/min，泵效恢复至 0.41")),
]

# alert_id → (order_id, status, extra)
_SEED_ORDERS: list[dict] = [
    dict(order_id="ord-seed-01", alert_id="alt-seed-01", priority="预警",
         well_id="W-3", status=WorkOrderStatus.PENDING),
    dict(order_id="ord-seed-02", alert_id="alt-seed-02", priority="紧急",
         well_id="W-7", status=WorkOrderStatus.PENDING),
    dict(order_id="ord-seed-03", alert_id="alt-seed-05", priority="预警",
         well_id="W-4", status=WorkOrderStatus.PROCESSING,
         assignee="张工", actions_taken="已降低钻压并循环观察，泥浆池补加重晶石"),
    dict(order_id="ord-seed-04", alert_id="alt-seed-08", priority="预警",
         well_id="W-2", status=WorkOrderStatus.RESOLVED,
         assignee="张工", resolution="热洗节流阀后压力回落至 3.0MPa，持续观察 4 小时"),
    dict(order_id="ord-seed-05", alert_id="alt-seed-09", priority="预警",
         well_id="W-3", status=WorkOrderStatus.CLOSED,
         assignee="李工", resolution="冲次由 6 次/min 调至 4 次/min，泵效恢复至 0.41",
         actual_cause="地层供液不足，沉没度持续下降导致泵效降低"),
]

# 候选沉淀队列：2 条待审核（工单闭环 + 高频告警）
_SEED_CANDIDATES: list[dict] = [
    dict(candidate_id="cand-seed-01", source_type="workorder", source_id="ord-seed-05",
         title="W-3 处置案例：泵效低于阈限", doc_type="案例",
         source_ref="工单 ord-seed-05",
         text="现象：W-3 泵效 0.30 低于阈限 0.35（等级 预警）。\n"
              "处置：冲次由 6 次/min 调至 4 次/min，泵效恢复至 0.41。\n"
              "实际原因：地层供液不足，沉没度持续下降导致泵效降低。",
         tags=["W-3", "预警", "泵效", "供液不足"]),
    dict(candidate_id="cand-seed-02", source_type="alert_dedup", source_id="dk-w7-pressure",
         title="高频告警处置要点：W-7 井口压力超上限", doc_type="案例",
         source_ref="告警聚合 dk-w7-pressure",
         text="来源 safety_risk 在 W-7 范围内去重窗口内反复出现（3 次）。\n"
              "原因：W-7 井口压力超上限。\n"
              "建议纳入巡检重点并复核根因，必要时升级工艺改造。",
         tags=["W-7", "safety_risk", "压力"]),
]

# 扩充知识文档（在 sim 5 篇基础上补至 12 篇，覆盖各井主题）
_SEED_EXTRA_DOCS: list[dict] = [
    dict(title="采油井日常巡检要点", doc_type="规程", source_ref="《采油井巡检管理规定》第 2 章",
         text="采油井每班巡检一次，重点检查抽油机运行声音、曲柄销紧固状态、电机温度与电流。"
              "发现异响、电流异常波动时应立即上报并加密巡检频次。",
         tags=["抽油机", "巡检", "电流", "W-1"]),
    dict(title="气井 H2S 监测与防护细则", doc_type="预案", source_ref="《气井安全生产细则》第 6 章",
         text="含硫气井应配备固定式与便携式 H2S 检测仪。周界浓度达到 10ppm 时启动预警响应，"
              "20ppm 时人员撤离至上风向并启动应急联动，处置全程佩戴正压式呼吸器。",
         tags=["H2S", "采气", "应急", "W-2"]),
    dict(title="钻井井控作业指导书", doc_type="预案", source_ref="《钻井井控管理规定》第 3 章",
         text="钻井作业必须连续监控泥浆密度与液面。密度低于设计下限或池液面异常上涨时，"
              "立即停止钻进、关井求压，按井控预案分级响应。",
         tags=["钻井", "井涌", "泥浆密度", "W-4"]),
    dict(title="抽油机电机电流异常诊断手册", doc_type="规程", source_ref="《设备诊断手册》第 8 节",
         text="上行电流波动超过基线 15% 时，依次排查平衡块位置、皮带张紧度、减速箱油位与"
              "电机轴承状态。平衡度应保持在 85%~115% 区间。",
         tags=["电流", "抽油机", "诊断", "W-5"]),
    dict(title="采气井冬季保温与防冻堵措施", doc_type="规程", source_ref="《冬季生产管理规定》第 4 章",
         text="入冬前完成井口保温层检查。井口温度异常升高需先排除表计日照直射等假异常；"
              "节流部位易发生冰堵，应关注节流前后压差变化并及时热洗。",
         tags=["温度", "采气", "节流", "W-6"]),
    dict(title="W-7 井口压力异常处置案例（2026-08）", doc_type="案例", source_ref="W-7 压力异常复盘报告",
         text="2026-08 W-7 井口压力 3.6MPa 超安全上限 3.2MPa。处置：关井节流降压至 2.8MPa，"
              "排查为地面管线结垢导致回压升高，酸洗管线后恢复生产。",
         tags=["W-7", "压力", "案例", "井控"]),
    dict(title="井场值班交接班规范", doc_type="规程", source_ref="《值班管理制度》第 1 章",
         text="交接班必须当面交接未闭环告警与工单，逐项确认状态与处置进展。"
              "紧急告警不得跨班挂起，确认超时将自动升级至值班班长。",
         tags=["值班", "交接班", "告警", "工单"]),
]


async def seed_alerts_orders(alert_repo, order_repo, candidate_repo) -> int:
    """空库时灌入种子告警/工单/候选；返回灌入的告警数。"""
    if await alert_repo.count() > 0:
        return 0

    alerts_by_id: dict[str, Alert] = {}
    for spec in _SEED_ALERTS:
        resolved = spec.pop("resolved", None)
        alert = Alert(**spec, last_seen=spec["first_seen"])
        if alert.status is AlertStatus.ACKNOWLEDGED:
            alert.acknowledged_by = "值班员"
            alert.acknowledged_at = spec["first_seen"] + timedelta(minutes=8)
        if resolved:
            by, resolution = resolved
            alert.resolved_by = by
            alert.resolution = resolution
            alert.resolved_at = spec["first_seen"] + timedelta(minutes=40)
        alerts_by_id[alert.alert_id] = alert
        await alert_repo.save(alert)

    for spec in _SEED_ORDERS:
        alert = alerts_by_id[spec["alert_id"]]
        order = WorkOrder(
            order_id=spec["order_id"], alert_id=spec["alert_id"],
            title=f"[{spec['priority']}] {alert.cause}",
            priority=spec["priority"], well_id=spec["well_id"],
            status=spec["status"],
            assignee=spec.get("assignee"),
            actions_taken=spec.get("actions_taken"),
            resolution=spec.get("resolution"),
            actual_cause=spec.get("actual_cause"),
            created_at=alert.first_seen,
            updated_at=alert.first_seen,
        )
        if spec["status"] is WorkOrderStatus.PROCESSING:
            order.escalations.append(EscalationRecord(
                ts=alert.first_seen + timedelta(minutes=5), kind="status",
                from_level="pending", to_level="processing", notified=[],
                note=f"指派给 {spec.get('assignee')}",
            ))
        if spec["status"] in (WorkOrderStatus.RESOLVED, WorkOrderStatus.CLOSED):
            order.resolved_at = alert.resolved_at
            order.escalations.append(EscalationRecord(
                ts=alert.first_seen + timedelta(minutes=5), kind="status",
                from_level="pending", to_level="processing",
                notified=[], note=f"指派给 {spec.get('assignee')}",
            ))
            order.escalations.append(EscalationRecord(
                ts=alert.resolved_at, kind="status",
                from_level="processing", to_level="resolved",
                notified=[], note=f"处置完成：{spec.get('resolution')}",
            ))
        if spec["status"] is WorkOrderStatus.CLOSED:
            order.closed_at = (alert.resolved_at or alert.first_seen) + timedelta(minutes=20)
            order.updated_at = order.closed_at
            order.escalations.append(EscalationRecord(
                ts=order.closed_at, kind="status",
                from_level="resolved", to_level="closed",
                notified=[], note=f"关闭工单，实际原因：{spec.get('actual_cause')}",
            ))
        await order_repo.save(order)

    for spec in _SEED_CANDIDATES:
        await candidate_repo.save(KBCandidate(**spec))

    logger.info("pg_repo.seeded", alerts=len(_SEED_ALERTS),
                orders=len(_SEED_ORDERS), candidates=len(_SEED_CANDIDATES))
    return len(_SEED_ALERTS)


async def seed_extra_kb_docs(kb_service, base_count: int = 5) -> int:
    """KB 仅有 sim 基础种子（base_count 篇）时，扩充至 12 篇。"""
    current = await kb_service._docs.count()  # noqa: SLF001 - 服务内聚种子逻辑
    if current > base_count:
        return 0
    for spec in _SEED_EXTRA_DOCS:
        await kb_service.create_document(
            title=spec["title"], doc_type=spec["doc_type"],
            source_ref=spec["source_ref"], text=spec["text"],
            tags=list(spec["tags"]), background=False,
        )
    logger.info("pg_repo.kb_extra_seeded", count=len(_SEED_EXTRA_DOCS))
    return len(_SEED_EXTRA_DOCS)
