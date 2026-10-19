"""告警处置服务：持久化、去重聚合、分级通知、超时升级、人工确认与工单闭环。

状态机（非法流转抛 ConflictError）：
- 告警：active → acknowledged → resolved
- 工单：pending → processing → resolved → closed

超时策略（sweep_timeouts 周期扫描）：
- active 告警超过 ACK_TIMEOUT 未确认 → 升一级并通知值班班长
- pending 工单超过 ORDER_TIMEOUT 未接单 → 记录升级并通知值班班长
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import structlog

from libs.api.errors import ConflictError, NotFoundError
from libs.deterministic import AlertDeduplicator
from libs.schemas import Level
from libs.schemas.alerts import (
    Alert,
    AlertStatus,
    EscalationRecord,
    WorkOrder,
    WorkOrderStatus,
)
from repositories.alert_repo import AlertRepository, WorkOrderRepository

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # 避免运行时循环依赖
    from services.kb_service import KBService

logger = structlog.get_logger(__name__)

# 等级 → 通知渠道 / 目标
CHANNEL_MAP: dict[str, tuple[list[str], list[str]]] = {
    Level.INFO.value: (["值班界面"], ["值班员"]),
    Level.WATCH.value: (["值班界面"], ["值班员"]),
    Level.WARNING.value: (["IM", "短信"], ["值班员"]),
    Level.CRITICAL.value: (["电话", "短信", "声光"], ["值班员", "值班班长"]),
}

# 确认超时：按告警当前等级（秒）
ACK_TIMEOUT: dict[str, float] = {
    Level.CRITICAL.value: 300.0,   # 紧急 5 分钟未确认即升级
    Level.WARNING.value: 1800.0,   # 预警 30 分钟
}

# 工单接单超时（秒）
ORDER_TIMEOUT: dict[str, float] = {
    Level.CRITICAL.value: 600.0,
    Level.WARNING.value: 3600.0,
}

# 触发工单生成的最低等级
ORDER_LEVELS = {Level.WARNING.value, Level.CRITICAL.value}

# 告警状态机：允许的目标状态
_ALERT_TRANSITIONS: dict[AlertStatus, set[AlertStatus]] = {
    AlertStatus.ACTIVE: {AlertStatus.ACKNOWLEDGED, AlertStatus.RESOLVED},
    AlertStatus.ACKNOWLEDGED: {AlertStatus.RESOLVED},
    AlertStatus.RESOLVED: set(),
}

# 工单状态机：允许的目标状态
_ORDER_TRANSITIONS: dict[WorkOrderStatus, set[WorkOrderStatus]] = {
    WorkOrderStatus.PENDING: {WorkOrderStatus.PROCESSING},
    WorkOrderStatus.PROCESSING: {WorkOrderStatus.RESOLVED},
    WorkOrderStatus.RESOLVED: {WorkOrderStatus.CLOSED},
    WorkOrderStatus.CLOSED: set(),
}

_LEVEL_ORDER = {Level.INFO.value: 0, Level.WATCH.value: 1,
                Level.WARNING.value: 2, Level.CRITICAL.value: 3}
_ORDER_LEVEL = {v: k for k, v in _LEVEL_ORDER.items()}

SWEEP_INTERVAL_SECONDS = 30.0


class AlertService:
    """告警 + 工单领域服务（每个依赖容器持有一个实例）。"""

    def __init__(
        self,
        alert_repo: AlertRepository,
        order_repo: WorkOrderRepository,
        dedup_window_minutes: int = 10,
        sweep_interval: float = SWEEP_INTERVAL_SECONDS,
    ) -> None:
        self._alerts = alert_repo
        self._orders = order_repo
        self._dedup = AlertDeduplicator(window_minutes=dedup_window_minutes)
        self._sweep_interval = sweep_interval
        self._sweep_task: asyncio.Task | None = None
        self._kb: "KBService | None" = None

    def set_kb_service(self, kb: "KBService") -> None:
        """注入知识库服务（容器装配时调用），启用经验自进化沉淀钩子。"""
        self._kb = kb

    # ---------------- 告警接入 ----------------

    async def ingest(
        self,
        source: str,
        cause: str,
        level: str,
        scope: str = "",
        content: str = "",
        trace_id: str = "",
        now: datetime | None = None,
    ) -> tuple[Alert, bool]:
        """接入一条告警事件：去重聚合后落库；返回 (告警, 是否新建)。

        - 窗口内同源同因：仅累计命中次数；等级上升则升级（重算通知目标）
        - 预警 / 紧急等级的新告警自动生成工单
        """
        now = now or datetime.now(timezone.utc)
        outcome = self._dedup.aggregate(source, cause, level, scope, now=now)

        if not outcome.is_new:
            alert = await self._find_by_dedup_key(outcome.dedup_key)
            if alert is None:  # 状态已过期等边界：按新告警处理
                outcome.is_new = True
            else:
                def _hit(a: Alert) -> None:
                    a.hit_count = outcome.count
                    a.last_seen = now
                    if outcome.suppressed:
                        a.suppressed_count += 1
                    if outcome.escalated:
                        a.escalations.append(EscalationRecord(
                            ts=now, kind="dedup",
                            from_level=a.level, to_level=level,
                            notified=CHANNEL_MAP.get(level, ([], []))[1],
                            note="去重窗口内等级上升，按新等级重新通知",
                        ))
                        a.level = level

                await self._alerts.update(alert.alert_id, _hit)
                logger.info("alert.dedup_hit", alert_id=alert.alert_id,
                            count=outcome.count, escalated=outcome.escalated)
                # 高频同源告警（窗口内 ≥3 次）→ 沉淀风险处置要点候选（幂等）
                if outcome.count >= 3:
                    await self._distill_frequent_alert(
                        outcome.dedup_key, source, cause, scope, outcome.count)
                return alert, False

        alert = Alert(
            dedup_key=outcome.dedup_key, level=level, source=source, cause=cause,
            scope=scope, content=content or cause, trace_id=trace_id,
            first_seen=now, last_seen=now,
        )
        await self._alerts.save(alert)
        logger.info("alert.created", alert_id=alert.alert_id, level=level,
                    source=source, cause=cause, scope=scope)

        if level in ORDER_LEVELS:
            await self._create_order(alert, now)
        return alert, True

    async def _find_by_dedup_key(self, dedup_key: str) -> Alert | None:
        """取该去重键最近一条告警（键可跨窗口复用，历史告警可能有多条）。"""
        items = await self._alerts.list(lambda a: a.dedup_key == dedup_key)
        if not items:
            return None
        items.sort(key=lambda a: a.last_seen, reverse=True)
        return items[0]

    async def _create_order(self, alert: Alert, now: datetime) -> WorkOrder:
        order = WorkOrder(
            alert_id=alert.alert_id,
            title=f"[{alert.level}] {alert.cause}",
            priority=alert.level,
            well_id=alert.scope,
            created_at=now,
            updated_at=now,
        )
        await self._orders.save(order)
        logger.info("workorder.created", order_id=order.order_id,
                    alert_id=alert.alert_id, priority=order.priority)
        return order

    # ---------------- 告警状态机 ----------------

    async def acknowledge(self, alert_id: str, operator: str) -> Alert:
        """确认告警（active → acknowledged）。"""
        return await self._transition_alert(
            alert_id, AlertStatus.ACKNOWLEDGED, operator,
            lambda a, now: (
                setattr(a, "acknowledged_by", operator),
                setattr(a, "acknowledged_at", now),
            ),
            note=f"{operator} 确认告警",
        )

    async def resolve(self, alert_id: str, operator: str, resolution: str) -> Alert:
        """关闭告警（active/acknowledged → resolved）。"""
        return await self._transition_alert(
            alert_id, AlertStatus.RESOLVED, operator,
            lambda a, now: (
                setattr(a, "resolved_by", operator),
                setattr(a, "resolved_at", now),
                setattr(a, "resolution", resolution),
            ),
            note=f"{operator} 解决：{resolution}",
        )

    async def _transition_alert(
        self, alert_id: str, target: AlertStatus, operator: str,
        apply,  # Callable[[Alert, datetime], None]
        note: str = "",
    ) -> Alert:
        alert = await self._alerts.get_by_id(alert_id)
        if alert is None:
            raise NotFoundError(f"告警不存在：{alert_id}")
        if target not in _ALERT_TRANSITIONS.get(alert.status, set()):
            raise ConflictError(
                f"告警状态不允许从 {alert.status.value} 流转到 {target.value}",
                details={"alert_id": alert_id, "current": alert.status.value,
                         "target": target.value},
            )
        now = datetime.now(timezone.utc)
        from_status = alert.status

        def _apply(a: Alert) -> None:
            apply(a, now)
            a.status = target
            a.escalations.append(EscalationRecord(
                ts=now, kind="status",
                from_level=from_status.value, to_level=target.value,
                notified=[operator], note=note,
            ))

        updated = await self._alerts.update(alert_id, _apply)
        logger.info("alert.transition", alert_id=alert_id,
                    target=target.value, operator=operator)
        return updated  # type: ignore[return-value]

    # ---------------- 工单状态机 ----------------

    async def assign_order(self, order_id: str, assignee: str, operator: str,
                           actions_taken: str | None = None) -> WorkOrder:
        """接单/指派（pending → processing）。"""
        return await self._transition_order(
            order_id, WorkOrderStatus.PROCESSING, operator,
            lambda o, now: (
                setattr(o, "assignee", assignee),
                setattr(o, "actions_taken", actions_taken),
            ),
            note=f"指派给 {assignee}",
        )

    async def resolve_order(self, order_id: str, operator: str,
                            resolution: str) -> WorkOrder:
        """完成工单（processing → resolved）。"""
        return await self._transition_order(
            order_id, WorkOrderStatus.RESOLVED, operator,
            lambda o, now: (
                setattr(o, "resolution", resolution),
                setattr(o, "resolved_at", now),
            ),
            note=f"处置完成：{resolution}",
        )

    async def close_order(self, order_id: str, operator: str,
                          actual_cause: str) -> WorkOrder:
        """关闭工单（resolved → closed），回填实际原因形成闭环。"""
        order = await self._transition_order(
            order_id, WorkOrderStatus.CLOSED, operator,
            lambda o, now: (
                setattr(o, "actual_cause", actual_cause),
                setattr(o, "closed_at", now),
            ),
            note=f"关闭工单，实际原因：{actual_cause}",
        )
        # 工单闭环 → 沉淀处置案例候选（幂等，失败不影响主流程）
        await self._distill_closed_order(order)
        return order

    # ---------------- 经验沉淀钩子（自进化管道） ----------------

    async def _distill_closed_order(self, order: WorkOrder) -> None:
        """闭环工单 → 案例候选：现象/处置/实际原因三要素。"""
        if self._kb is None:
            return
        try:
            alert = await self._alerts.get_by_id(order.alert_id)
            phenomenon = (alert.content or alert.cause) if alert else order.title
            scope = order.well_id or (alert.scope if alert else "") or "井场"
            await self._kb.submit_candidate(
                source_type="workorder", source_id=order.order_id,
                title=f"{scope} 处置案例：{order.title}",
                doc_type="案例",
                source_ref=f"工单 {order.order_id}",
                text=(f"现象：{phenomenon}（等级 {order.priority}）。\n"
                      f"处置：{order.resolution or '按规程处置'}。\n"
                      f"实际原因：{order.actual_cause}。"),
                tags=[t for t in (scope, order.priority) if t],
            )
        except Exception:  # noqa: BLE001 - 沉淀失败不影响工单闭环
            logger.exception("kb.distill_order_failed", order_id=order.order_id)

    async def _distill_frequent_alert(self, dedup_key: str, source: str,
                                      cause: str, scope: str, count: int) -> None:
        """高频同源告警 → 风险处置要点候选（幂等键=去重键）。"""
        if self._kb is None:
            return
        try:
            await self._kb.submit_candidate(
                source_type="alert_dedup", source_id=dedup_key,
                title=f"高频告警处置要点：{cause}",
                doc_type="案例",
                source_ref=f"告警聚合 {dedup_key}",
                text=(f"来源 {source} 在 {scope or '井场'} 范围内"
                      f"去重窗口内反复出现（{count} 次）。\n"
                      f"原因：{cause}。\n建议纳入巡检重点并复核根因，"
                      "必要时升级工艺改造。"),
                tags=[t for t in (scope, source) if t],
            )
        except Exception:  # noqa: BLE001
            logger.exception("kb.distill_alert_failed", dedup_key=dedup_key)

    async def _transition_order(
        self, order_id: str, target: WorkOrderStatus, operator: str,
        apply, note: str = "",
    ) -> WorkOrder:
        order = await self._orders.get_by_id(order_id)
        if order is None:
            raise NotFoundError(f"工单不存在：{order_id}")
        if target not in _ORDER_TRANSITIONS.get(order.status, set()):
            raise ConflictError(
                f"工单状态不允许从 {order.status.value} 流转到 {target.value}",
                details={"order_id": order_id, "current": order.status.value,
                         "target": target.value},
            )
        now = datetime.now(timezone.utc)
        from_status = order.status

        def _apply(o: WorkOrder) -> None:
            apply(o, now)
            o.status = target
            o.updated_at = now
            o.escalations.append(EscalationRecord(
                ts=now, kind="status",
                from_level=from_status.value, to_level=target.value,
                notified=[operator], note=note,
            ))

        updated = await self._orders.update(order_id, _apply)
        logger.info("workorder.transition", order_id=order_id,
                    target=target.value, operator=operator)
        return updated  # type: ignore[return-value]

    # ---------------- 超时升级 ----------------

    async def sweep_timeouts(self, now: datetime | None = None) -> dict[str, int]:
        """扫描超时项并升级；返回 {alerts_escalated, orders_escalated}。"""
        now = now or datetime.now(timezone.utc)
        alerts_n = await self._sweep_alert_timeouts(now)
        orders_n = await self._sweep_order_timeouts(now)
        if alerts_n or orders_n:
            logger.info("alert.sweep", alerts=alerts_n, orders=orders_n)
        return {"alerts_escalated": alerts_n, "orders_escalated": orders_n}

    async def _sweep_alert_timeouts(self, now: datetime) -> int:
        actives = await self._alerts.query(status=AlertStatus.ACTIVE)
        count = 0
        for alert in actives:
            timeout = ACK_TIMEOUT.get(alert.level)
            if timeout is None or (now - alert.last_seen) < timedelta(seconds=timeout):
                continue
            new_level = _ORDER_LEVEL[min(_LEVEL_ORDER[alert.level] + 1,
                                         _LEVEL_ORDER[Level.CRITICAL.value])]
            targets = CHANNEL_MAP[new_level][1]

            def _escalate(a: Alert, nl: str = new_level, tg: list[str] = list(targets)) -> None:
                a.escalations.append(EscalationRecord(
                    ts=now, kind="timeout",
                    from_level=a.level, to_level=nl, notified=tg,
                    note="确认超时，自动升级并通知值班班长",
                ))
                a.level = nl
                a.last_seen = now  # 重置窗口，避免每轮扫描重复升级

            await self._alerts.update(alert.alert_id, _escalate)
            count += 1
        return count

    async def _sweep_order_timeouts(self, now: datetime) -> int:
        pendings = await self._orders.query(status=WorkOrderStatus.PENDING)
        count = 0
        for order in pendings:
            timeout = ORDER_TIMEOUT.get(order.priority)
            if timeout is None or (now - order.updated_at) < timedelta(seconds=timeout):
                continue

            def _escalate(o: WorkOrder) -> None:
                o.escalations.append(EscalationRecord(
                    ts=now, kind="timeout",
                    from_level=o.priority, to_level=o.priority,
                    notified=["值班班长"],
                    note="工单接单超时，已通知值班班长督办",
                ))
                o.updated_at = now

            await self._orders.update(order.order_id, _escalate)
            count += 1
        return count

    # ---------------- 后台扫描 ----------------

    async def start_sweeper(self) -> None:
        """启动后台超时扫描（容器启动时调用）。"""
        if self._sweep_task is not None:
            return

        async def _loop() -> None:
            while True:
                await asyncio.sleep(self._sweep_interval)
                try:
                    await self.sweep_timeouts()
                except Exception:  # noqa: BLE001 - 扫描失败不影响主链路
                    logger.exception("alert.sweep_failed")

        self._sweep_task = asyncio.create_task(_loop())

    async def stop_sweeper(self) -> None:
        """停止后台扫描（容器关闭时调用）。"""
        if self._sweep_task is not None:
            self._sweep_task.cancel()
            self._sweep_task = None
