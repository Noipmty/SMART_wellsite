"""SCADA 时序数据仿真（mock）—— 等价于 TDengine 查询结果。

内置故障场景：W-3 采油井供液不足
（井口日产量 / 泵效 / 沉没度 / 电流 自昨日 20:00 起持续下行，且今日 02:00~04:00 存在数据缺口；
起始时刻定在昨夜使任意运行时段内趋势均已累积到可判定量级）。

数据形态（贴近真实 SCADA）：
- 整点小时点：基线 + 日内平滑慢漂移（日波/半日波叠加，相邻时刻连续，不做逐点白噪声）
  + 故障趋势（线性 slope）；
- 实时点：查询窗口覆盖当前时刻时追加，取连续基线在"现在"的估值 +
  分钟级测量噪声（每分钟一阶）与 10s 桶微抖（供大屏轮询感知"在动"）；
- 不生成未来时刻的数据：曲线末端始终跟随墙钟推进。
"""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timedelta

from libs.schemas import PerceptionEvent, TelemetryPoint, TelemetryResult
from sim.points import spec_by_suffix, split_tag
from sim.timebase import now_dt, today

_FMT = "%Y-%m-%d %H:%M"
_FMT_S = "%Y-%m-%d %H:%M:%S"

# well_type: {suffix: (base, 日内平滑漂移振幅)} —— 振幅按工业实测量级收敛（缓变指标 <1%）
BASES: dict[str, dict[str, tuple[float, float]]] = {
    "oil": {
        "daily_oil_prod": (22.0, 0.15),
        "daily_oil_clean": (20.5, 0.12),
        "pump_efficiency": (0.45, 0.008),
        "submergence": (320.0, 2.0),
        "current": (38.0, 0.4),
        "casing_pressure": (1.2, 0.02),
        "stroke_freq": (6.0, 0.0),
    },
    "gas": {
        "daily_gas_prod": (5.2, 0.06),
        "wellhead_pressure": (2.4, 0.03),
        "throttle_in_pressure": (3.1, 0.03),
        "wellhead_temp": (24.0, 0.3),
    },
    "drilling": {
        "wob": (120.0, 1.5),
        "rpm": (90.0, 1.0),
        "mud_density": (1.25, 0.005),
    },
}


def _scenario_start() -> datetime:
    """故障起始时刻：昨日 20:00（动态跟随墙钟，跨夜下行使趋势尽早达到可判定幅度）。"""
    return today() + timedelta(hours=-4)


# 每小时变化量（起始时刻之后生效；量级保证运行满 ~3h 即越过 10% 相对降幅判定线）
SCENARIO_SLOPE: dict[tuple[str, str], float] = {
    ("W-3", "daily_oil_prod"): -0.8,
    ("W-3", "daily_oil_clean"): -0.7,
    ("W-3", "pump_efficiency"): -0.02,
    ("W-3", "submergence"): -25.0,
    ("W-3", "current"): -2.0,
}

# 数据断档（模拟采集中断）
def _gaps_today() -> dict[tuple[str, str], list[tuple[datetime, datetime]]]:
    t0 = today()
    return {
        ("W-3", "daily_oil_prod"): [(t0 + timedelta(hours=2), t0 + timedelta(hours=4))],
        ("W-3", "pump_efficiency"): [(t0 + timedelta(hours=2), t0 + timedelta(hours=4))],
        ("W-3", "submergence"): [(t0 + timedelta(hours=2), t0 + timedelta(hours=4))],
        ("W-3", "current"): [(t0 + timedelta(hours=2), t0 + timedelta(hours=4))],
    }


def parse_dt(text: str) -> datetime:
    """解析 "YYYY-MM-DD" 或 "YYYY-MM-DD HH:MM"。"""
    text = str(text).strip()
    if len(text) == 10:
        text = f"{text} 00:00"
    return datetime.strptime(text[:16], _FMT)


def _hash01(key: str) -> float:
    """MD5 确定性 [0,1) 散列。"""
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def _smooth(tag: str, day_str: str, hour_f: float, amp: float) -> float:
    """日内平滑慢漂移：日波（权重 .65）+ 半日波（权重 .35），相位按 tag/日期确定性取定。

    与逐点独立白噪声的区别：任意相邻时刻取值连续相关，曲线只有缓变起伏，无锯齿尖峰。
    """
    seed = f"{tag}|{day_str}"
    p1 = _hash01(seed + "|p1") * 2 * math.pi
    p2 = _hash01(seed + "|p2") * 2 * math.pi
    return (
        amp * 0.65 * math.sin(2 * math.pi * hour_f / 24 + p1)
        + amp * 0.35 * math.sin(2 * math.pi * hour_f / 12 + p2)
    )


def _well_type(well_id: str) -> str:
    from sim.registry import WELLS

    w = WELLS.get(well_id)
    return w.well_type if w else "oil"


def _base_value_at(
    tag: str, dt: datetime, base: float, amp: float,
    slope: float, scenario_start: datetime,
) -> float:
    """连续基线估值：基线 + 平滑漂移 + 故障趋势（任意时刻可求值）。"""
    hour_f = dt.hour + dt.minute / 60 + dt.second / 3600
    val = base + _smooth(tag, dt.strftime("%Y-%m-%d"), hour_f, amp)
    if slope and dt >= scenario_start:
        val += slope * (dt - scenario_start).total_seconds() / 3600
    return val


def query_series(tag: str, start: str, end: str) -> TelemetryResult:
    """查询单个 tag 的时序数据。"""
    well_id, suffix = split_tag(tag)
    spec = spec_by_suffix(suffix)
    metric = spec.metric if spec else suffix
    unit = spec.unit if spec else ""
    wtype = _well_type(well_id)

    base, amp = BASES.get(wtype, {}).get(suffix, (1.0, 0.05))
    slope = SCENARIO_SLOPE.get((well_id, suffix), 0.0)
    scenario_start = _scenario_start()
    gap_windows = _gaps_today().get((well_id, suffix), [])

    t0, t1 = parse_dt(start), parse_dt(end)
    now = now_dt()
    upper = min(t1, now)  # 不生成未来时刻的数据

    series: list[TelemetryPoint] = []
    gap_hits: list[str] = []
    cur = t0
    while cur <= upper:
        ts = cur.strftime(_FMT)
        if any(a <= cur <= b for a, b in gap_windows):
            gap_hits.append(ts)
        else:
            val = _base_value_at(tag, cur, base, amp, slope, scenario_start)
            series.append(TelemetryPoint(ts=ts, value=round(val, 3)))
        cur += timedelta(hours=1)

    # ---- 实时点：窗口覆盖当前时刻且当前不在缺口内时追加（SCADA 最新上报值） ----
    in_gap_now = any(a <= now <= b for a, b in gap_windows)
    if t0 <= now <= t1 and not in_gap_now:
        live_val = _base_value_at(tag, now, base, amp, slope, scenario_start)
        minute_key = now.strftime("%Y-%m-%d %H:%M")
        live_val += (_hash01(f"{tag}|{minute_key}") - 0.5) * 2 * amp * 0.12  # 分钟级测量噪声
        bucket10s = now.second // 10
        live_val += (_hash01(f"{tag}|{minute_key}|{bucket10s}") - 0.5) * 2 * amp * 0.05
        series.append(TelemetryPoint(
            ts=now.strftime(_FMT_S), value=round(live_val, 3),
        ))

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
