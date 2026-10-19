"""告警去重聚合：同源同因事件 10 分钟内聚合为一条，防告警风暴。

对应提示词执行层"去重聚合"与"告警疲劳"。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass
class DedupState:
    key: str
    first_seen: datetime
    last_seen: datetime
    count: int = 1
    level: str = "提醒"


@dataclass
class DedupOutcome:
    dedup_key: str
    is_new: bool
    count: int
    escalated: bool = False
    suppressed: bool = False


_LEVEL_ORDER = {"提示": 0, "提醒": 1, "预警": 2, "紧急": 3}


class AlertDeduplicator:
    """内存去重聚合器（生产可换 Redis）。"""

    def __init__(self, window_minutes: int = 10) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._states: dict[str, DedupState] = {}

    @staticmethod
    def make_key(source: str, cause: str, scope: str = "") -> str:
        raw = f"{source}|{cause}|{scope}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]

    def aggregate(self, source: str, cause: str, level: str, scope: str = "",
                  now: datetime | None = None) -> DedupOutcome:
        """聚合判定：返回是否新事件 / 命中次数 / 是否升级 / 是否被抑制。"""
        now = now or datetime.now(timezone.utc)
        key = self.make_key(source, cause, scope)
        st = self._states.get(key)

        if st is None or (now - st.last_seen) > self._window:
            self._states[key] = DedupState(key=key, first_seen=now, last_seen=now, count=1, level=level)
            return DedupOutcome(dedup_key=key, is_new=True, count=1)

        st.last_seen = now
        st.count += 1
        escalated = _LEVEL_ORDER.get(level, 0) > _LEVEL_ORDER.get(st.level, 0)
        if escalated:
            st.level = level
        return DedupOutcome(dedup_key=key, is_new=False, count=st.count,
                            escalated=escalated, suppressed=not escalated)
