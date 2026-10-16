"""事件日历（Event Calendar）—— mock 数据源。

检修 / 停电 / 限产记录参与归因：已知事件直接引用，禁止误判为设备故障。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

_TS_FMT = "%Y-%m-%d %H:%M"


@dataclass(frozen=True)
class CalendarEvent:
    event_type: str        # 检修 / 停电 / 限产
    wells: tuple[str, ...]
    start: str
    end: str
    desc: str

    def covers(self, well_id: str, ts: str) -> bool:
        """判断某井在 ts 时刻是否处于该事件区间内。"""
        if well_id not in self.wells:
            return False
        try:
            t = datetime.strptime(ts[:16], _TS_FMT)
            s = datetime.strptime(self.start, _TS_FMT)
            e = datetime.strptime(self.end, _TS_FMT)
        except ValueError:
            return False
        return s <= t <= e


CALENDAR: list[CalendarEvent] = [
    CalendarEvent("检修", ("W-1",), "2026-10-14 08:00", "2026-10-14 12:00",
                  "W-1 抽油机例行检修，计划停井 4 小时"),
    CalendarEvent("停电", ("W-5",), "2026-10-14 02:00", "2026-10-14 04:00",
                  "东区计划停电，W-5 停井 2 小时"),
    CalendarEvent("限产", ("W-7",), "2026-10-12 00:00", "2026-10-16 23:59",
                  "外输管线检修，W-7 限产 30%"),
    CalendarEvent("检修", ("W-2",), "2026-10-13 09:00", "2026-10-13 17:00",
                  "W-2 采气树阀门维护"),
]


def events_in_range(well_id: str | None, start: str, end: str) -> list[CalendarEvent]:
    """返回与给定井、时间段相交的事件日历条目。"""
    hits: list[CalendarEvent] = []
    for ev in CALENDAR:
        if well_id and well_id not in ev.wells:
            continue
        if _overlap(ev.start, ev.end, start, end):
            hits.append(ev)
    return hits


def find_event(well_id: str, ts: str) -> CalendarEvent | None:
    """查找某井在指定时刻命中的人工事件（用于归因排除）。"""
    for ev in CALENDAR:
        if ev.covers(well_id, ts):
            return ev
    return None


def _overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    try:
        a1 = datetime.strptime(a_start, _TS_FMT)
        a2 = datetime.strptime(a_end, _TS_FMT)
        b1 = datetime.strptime(b_start[:16], _TS_FMT)
        b2 = datetime.strptime(b_end[:16], _TS_FMT)
    except ValueError:
        return False
    return a1 <= b2 and b1 <= a2
