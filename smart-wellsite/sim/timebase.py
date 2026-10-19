"""仿真时间基准：所有 mock 场景相对"今天"生成，便于用「今天 / 昨天」自然提问。

注意：now/today 均为函数动态求值（后端常驻进程不能在 import 时冻结日期）；
TODAY/DATE 为兼容测试保留的模块级快照。
"""

from __future__ import annotations

from datetime import datetime, timedelta


def now_dt() -> datetime:
    """当前墙钟时刻（秒级）。"""
    return datetime.now().replace(microsecond=0)


def today() -> datetime:
    """今天零点（每次调用动态求值）。"""
    n = now_dt()
    return n.replace(hour=0, minute=0, second=0)


def today_str() -> str:
    """今天日期字符串 YYYY-MM-DD。"""
    return today().strftime("%Y-%m-%d")


def day(offset: int = 0) -> datetime:
    """相对今天偏移 day 的零点。"""
    return today() + timedelta(days=offset)


def at(offset: int, hhmm: str) -> str:
    """相对今天偏移 day、指定 HH:MM 的时刻字符串。"""
    h, m = (hhmm.split(":") + ["0", "0"])[:2]
    return (day(offset) + timedelta(hours=int(h), minutes=int(m))).strftime("%Y-%m-%d %H:%M")


# ---- 模块级快照（仅测试/一次性脚本兼容；业务代码请用 today()/today_str()） ----
TODAY: datetime = today()
DATE: str = today_str()
