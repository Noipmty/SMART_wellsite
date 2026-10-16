"""SCADA 时序数据仿真（mock）—— 等价于 TDengine 查询结果。

内置故障场景：今日 W-3 采油井供液不足
（井口日产量 / 泵效 / 沉没度 / 电流 自 08:00 起持续下行，且 02:00~04:00 存在数据缺口）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from libs.schemas import PerceptionEvent, TelemetryPoint, TelemetryResult
from sim.points import spec_by_suffix, split_tag
from sim.timebase import DATE, at

_FMT = "%Y-%m-%d %H:%M"

# well_type: {suffix: (base, noise_amplitude)}
BASES: dict[str, dict[str, tuple[float, float]]] = {
    "oil": {
        "daily_oil_prod": (22.0, 0.6),
        "daily_oil_clean": (20.5, 0.5),
        "pump_efficiency": (0.45, 0.02),
        "submergence": (320.0, 6.0),
        "current": (38.0, 1.2),
        "casing_pressure": (1.2, 0.05),
        "stroke_freq": (6.0, 0.0),
    },
    "gas": {
        "daily_gas_prod": (5.2, 0.2),
        "wellhead_pressure": (2.4, 0.08),
        "throttle_in_pressure": (3.1, 0.1),
        "wellhead_temp": (24.0, 0.8),
    },
    "drilling": {
        "wob": (120.0, 5.0),
        "rpm": (90.0, 3.0),
        "mud_density": (1.25, 0.02),
    },
}

SCENARIO_DATE = DATE
SCENARIO_START = at(0, "08:00")  # 故障起始时刻（此前保持基线）

# 每小时变化量（仅 SCENARIO_DATE 且 SCENARIO_START 之后生效）
SCENARIO_SLOPE: dict[tuple[str, str], float] = {
    ("W-3", "daily_oil_prod"): -0.4,
    ("W-3", "daily_oil_clean"): -0.35,
    ("W-3", "pump_efficiency"): -0.008,
    ("W-3", "submergence"): -12.0,
    ("W-3", "current"): -1.0,
}

# 数据断档（模拟采集中断）
GAPS: dict[tuple[str, str], list[tuple[str, str]]] = {
    ("W-3", "daily_oil_prod"): [(at(0, "02:00"), at(0, "04:00"))],
    ("W-3", "pump_efficiency"): [(at(0, "02:00"), at(0, "04:00"))],
    ("W-3", "submergence"): [(at(0, "02:00"), at(0, "04:00"))],
    ("W-3", "current"): [(at(0, "02:00"), at(0, "04:00"))],
}


def parse_dt(text: str) -> datetime:
    """解析 "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM"。"""
    text = str(text).strip()
    if len(text) == 10:
        text = f"{text} 00:00"
    return datetime.strptime(text[:16], _FMT)


def _noise(key: str, amp: float) -> float:
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    frac = int(h[:6], 16) / 0xFFFFFF
    return (frac - 0.5) * 2 * amp


def _well_type(well_id: str) -> str:
    from sim.registry import WELLS

    w = WELLS.get(well_id)
    return w.well_type if w else "oil"


def query_series(tag: str, start: str, end: str) -> TelemetryResult:
    """查询单个 tag 的时序数据。"""
    well_id, suffix = split_tag(tag)
    spec = spec_by_suffix(suffix)
    metric = spec.metric if spec else suffix
    unit = spec.unit if spec else ""
    wtype = _well_type(well_id)

    base, amp = BASES.get(wtype, {}).get(suffix, (1.0, 0.05))
    slope = SCENARIO_SLOPE.get((well_id, suffix), 0.0)
    gap_windows = [(parse_dt(a), parse_dt(b)) for a, b in GAPS.get((well_id, suffix), [])]

    t0, t1 = parse_dt(start), parse_dt(end)
    series: list[TelemetryPoint] = []
    gap_hits: list[str] = []
    cur = t0
    while cur <= t1:
        ts = cur.strftime(_FMT)
        if any(a <= cur <= b for a, b in gap_windows):
            gap_hits.append(ts)
        else:
            val = base + _noise(f"{tag}|{ts}", amp)
            if slope and cur.strftime("%Y-%m-%d") == SCENARIO_DATE and cur >= parse_dt(SCENARIO_START):
                hours = (cur - parse_dt(SCENARIO_START)).total_seconds() / 3600
                val += slope * hours
            series.append(TelemetryPoint(ts=ts, value=round(val, 3)))
        cur += timedelta(hours=1)

    quality: dict = {}
    if gap_hits:
        span = f"{gap_hits[0]}~{gap_hits[-1]}" if len(gap_hits) > 1 else gap_hits[0]
        quality["gap"] = [span]

    events: list[PerceptionEvent] = []
    if slope and series:
        first, last = series[0].value, series[-1].value
        direction = "下行" if last < first else "上行"
        events.append(
            PerceptionEvent(
                type="异常",
                source="data_collector",
                ts=series[-1].ts,
                payload={
                    "metric": metric,
                    "tag": tag,
                    "detail": f"{metric} 持续{direction}",
                    "from": first,
                    "to": last,
                },
            )
        )

    return TelemetryResult(tag=tag, metric=metric, unit=unit, series=series, quality=quality, events=events)
