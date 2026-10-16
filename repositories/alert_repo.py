"""告警与工单仓储：内存实现（真实部署换 PostgreSQL 绑定）。"""

from __future__ import annotations

from libs.schemas.alerts import Alert, AlertStatus, WorkOrder, WorkOrderStatus
from repositories.base import InMemoryRepository


class AlertRepository(InMemoryRepository[Alert]):
    """alert_id → Alert；支持状态/等级/井号过滤，按 last_seen 倒序。"""

    async def save(self, alert: Alert) -> Alert:
        return await self.add(alert.alert_id, alert)

    async def get_by_id(self, alert_id: str) -> Alert | None:
        return await self.get(alert_id)

    async def query(
        self,
        status: AlertStatus | None = None,
        level: str | None = None,
        well_id: str | None = None,
    ) -> list[Alert]:
        def predicate(a: Alert) -> bool:
            if status and a.status is not status:
                return False
            if level and a.level != level:
                return False
            if well_id and a.scope != well_id:
                return False
            return True

        items = await self.list(predicate)
        items.sort(key=lambda a: a.last_seen, reverse=True)
        return items


class WorkOrderRepository(InMemoryRepository[WorkOrder]):
    """order_id → WorkOrder；支持状态/指派人过滤，按 created_at 倒序。"""

    async def save(self, order: WorkOrder) -> WorkOrder:
        return await self.add(order.order_id, order)

    async def get_by_id(self, order_id: str) -> WorkOrder | None:
        return await self.get(order_id)

    async def query(
        self,
        status: WorkOrderStatus | None = None,
        assignee: str | None = None,
    ) -> list[WorkOrder]:
        def predicate(o: WorkOrder) -> bool:
            if status and o.status is not status:
                return False
            if assignee and o.assignee != assignee:
                return False
            return True

        items = await self.list(predicate)
        items.sort(key=lambda o: o.created_at, reverse=True)
        return items
