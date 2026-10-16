"""环境监测 + 视频智能 仿真（mock）。

环境场景：2026-10-14 W-7 井口 H2S 自 12:00 起快速爬升，15:30 达 12ppm（超过预警值 10）。
视频场景：CAM-03 检测到未戴安全帽（高风险事件需多帧二次确认）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

from libs.schemas import PerceptionEvent, TelemetryPoint
from sim.scada import parse_dt

_FMT = "%Y-%m-%d %H:%M"

ENV_THRESHOLDS: dict[str, dict[str, float]] = {
    "H2S": {"提醒": 5, "预警": 10, "紧急": 20},
    "可燃气体": {"提醒": 10, "预警": 25, "紧急": 50},
    "CO": {"提醒": 24, "预警": 50, "紧急": 100},
}
ENV_UNITS: dict[str, str] = {"H2S": "ppm", "可燃气体": "%LEL", "CO": "ppm"}
ENV_BASE: dict[str, float] = {"H2S": 2.0, "可燃气体": 4.0, "CO": 3.0}

# 环境场景：(well, metric) → 爬升参数
ENV_SCENARIOS: dict[tuple[str, str], dict] = {
    ("W-7", "H2S"): {
        "date": "2026-10-14",
        "ramp_start": "2026-10-14 12:00",
        "ramp_end": "2026-10-14 15:30",
        "from_val": 3.0,
        "to_val": 12.0,
    }
}


def _noise(key: str, amp: float) -> float:
    h = hashlib.md5(key.encode("utf-8")).hexdigest()
    return (int(h[:6], 16) / 0xFFFFFF - 0.5) * 2 * amp


def query_env(metric: str, well_id: str, start: str, end: str) -> tuple[list[TelemetryPoint], str]:
    """查询环境参数时序，返回 (系列, 趋势 up/down/flat)。"""
    base = ENV_BASE.get(metric, 1.0)
    amp = max(0.05 * base, 0.1)
    scen = ENV_SCENARIOS.get((well_id, metric))

    t0, t1 = parse_dt(start), parse_dt(end)
    series: list[TelemetryPoint] = []
    cur = t0
    while cur <= t1:
        ts = cur.strftime(_FMT)
        val = base + _noise(f"{well_id}|{metric}|{ts}", amp)
        if scen and cur.strftime("%Y-%m-%d") == scen["date"]:
            rs, re = parse_dt(scen["ramp_start"]), parse_dt(scen["ramp_end"])
            if cur >= re:
                val = scen["to_val"]
            elif cur >= rs:
                ratio = (cur - rs).total_seconds() / (re - rs).total_seconds()
                val = scen["from_val"] + (scen["to_val"] - scen["from_val"]) * ratio
        series.append(TelemetryPoint(ts=ts, value=round(val, 3)))
        cur += timedelta(hours=1)

    trend = "flat"
    if len(series) >= 2:
        delta = series[-1].value - series[0].value
        trend = "up" if delta > 0.5 else ("down" if delta < -0.5 else "flat")
    return series, trend


def level_for(metric: str, value: float) -> str | None:
    """按现场规程阈值判定等级。"""
    th = ENV_THRESHOLDS.get(metric)
    if not th:
        return None
    if value >= th["紧急"]:
        return "紧急"
    if value >= th["预警"]:
        return "预警"
    if value >= th["提醒"]:
        return "提醒"
    return None


# ----------------------- 视频智能 -----------------------

VIDEO_EVENTS: list[dict] = [
    {
        "cam_id": "CAM-03",
        "well": "W-7",
        "ts": "2026-10-14 15:22:01",
        "class": "未戴安全帽",
        "bbox": [102, 88, 160, 210],
        "conf": 0.92,
        "frames": 5,          # 连续命中帧数
        "perspectives": 1,    # 视角数
    },
    {
        "cam_id": "CAM-05",
        "well": "W-1",
        "ts": "2026-10-14 10:05:12",
        "class": "违规闯入",
        "bbox": [300, 120, 360, 300],
        "conf": 0.88,
        "frames": 4,
        "perspectives": 2,
    },
]


def query_video(cam_id: str | None, well_id: str | None, start: str, end: str) -> list[dict]:
    """查询视频检测事件（mock，未做时间过滤的简化返回）。"""
    out: list[dict] = []
    for ev in VIDEO_EVENTS:
        if cam_id and ev["cam_id"] != cam_id:
            continue
        if well_id and ev["well"] != well_id:
            continue
        out.append(ev)
    return out


def video_events_as_perception(events: list[dict], trace_id: str | None = None) -> list[PerceptionEvent]:
    """把视频检测转成感知事件（高风险事件已在 Agent 内二次确认）。"""
    result: list[PerceptionEvent] = []
    for ev in events:
        high_risk = ev["class"] in {"烟火", "油气泄漏", "违规闯入"}
        result.append(
            PerceptionEvent(
                type="视频告警",
                source="video_intelligence",
                ts=ev["ts"],
                level="预警" if not high_risk else "紧急",
                payload={k: v for k, v in ev.items() if k != "well"},
                trace_id=trace_id,
            )
        )
    return result


def describe_frame(ev: dict) -> str:
    """可选 LLM 增强的自然语言场景描述（基于画面事实，禁止脑补）。"""
    return (
        f"{ev['cam_id']} 画面显示 {ev.get('well', '')} 井场一名人员{ev['class']}"
        f"（置信度 {ev['conf']:.2f}），目标框 {ev['bbox']}。"
    )
