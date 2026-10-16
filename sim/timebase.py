"""仿真时间基准：所有 mock 场景相对"今天"生成，便于用「今天 / 昨天」自然提问。"""

from __future__ import annotations

from datetime import datetime, timedelta

TODAY: datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
DATE: str = TODAY.strftime("%Y-%m-%d")


def day(offset: int = 0) -> datetime:
    """相对今天偏移 day 的零点。"""
    return TODAY + timedelta(days=offset)


def at(offset: int, hhmm: str) -> str:
    """相对今天偏移 day、指定 HH:MM 的时刻字符串。"""
    h, m = (hhmm.split(":") + ["0", "0"])[:2]
    return (day(offset) + timedelta(hours=int(h), minutes=int(m))).strftime("%Y-%m-%d %H:%M")
