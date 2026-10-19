"""相对时间解析：把口语化时间表述换算为绝对区间。

规则（对应提示词"时间表述有歧义必须追问"）：
- 明确表述（今天 / 昨天 / 近 N 天 / 具体日期）→ 直接换算
- 歧义表述（上周 / 最近 / 那天 / 前几天）→ ambiguous=True，交值班助手澄清
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

_DT_FMT = "%Y-%m-%d %H:%M"
_DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?")

# 歧义表述
_AMBIGUOUS = ("上周", "上个月", "最近", "那天", "前几天", "前段时间", "之前", "有阵子")


@dataclass
class TimeParseResult:
    start: str | None = None
    end: str | None = None
    ambiguous: bool = False
    reason: str = ""

    @property
    def range(self) -> list[str] | None:
        if self.start and self.end:
            return [self.start, self.end]
        return None


def _day_bounds(d: datetime) -> tuple[str, str]:
    return d.strftime("%Y-%m-%d 00:00"), d.strftime("%Y-%m-%d 23:59")


def parse_time(text: str | None, now: datetime | None = None) -> TimeParseResult:
    """解析时间表述，返回绝对区间或标记歧义。"""
    if not text:
        return TimeParseResult(ambiguous=True, reason="未提供时间，需确认查询时间段")
    now = now or datetime.now()
    s = str(text).strip()

    # 具体日期（支持 2026-10-14 / 2026年10月14日）
    for m in _DATE_RE.finditer(s):
        y, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            d = datetime(y, mo, da)
        except ValueError:
            continue
        a, b = _day_bounds(d)
        return TimeParseResult(a, b, reason="解析具体日期")

    # 近 N 天 / 过去 N 天 / 最近 N 天
    m = re.search(r"(?:近|最近|过去|前)\s*(\d+)\s*(?:天|日)", s)
    if m:
        n = int(m.group(1))
        end = now
        start = now - timedelta(days=n)
        return TimeParseResult(start.strftime(_DT_FMT), end.strftime(_DT_FMT), reason=f"近 {n} 天")

    if "今天" in s or "今日" in s:
        a, b = _day_bounds(now)
        return TimeParseResult(a, b, reason="今天")
    if "昨天" in s or "昨日" in s:
        a, b = _day_bounds(now - timedelta(days=1))
        return TimeParseResult(a, b, reason="昨天")
    if "前天" in s:
        a, b = _day_bounds(now - timedelta(days=2))
        return TimeParseResult(a, b, reason="前天")

    # 歧义表述
    for kw in _AMBIGUOUS:
        if kw in s:
            return TimeParseResult(ambiguous=True, reason=f"时间表述“{kw}”有歧义，需确认具体时间段")

    # 形如 HH:MM 的纯时间
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        day = now.strftime("%Y-%m-%d")
        return TimeParseResult(f"{day} {int(m.group(1)):02d}:{m.group(2)}",
                               f"{day} 23:59", reason="当日指定时刻起")

    return TimeParseResult(ambiguous=True, reason="无法识别时间表述，需确认时间段")
