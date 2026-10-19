"""Agent 公共辅助：按井型取关键指标、趋势判定、序列摘要。"""

from __future__ import annotations

from libs.schemas import TelemetryResult
from sim.points import spec_by_suffix, tag_for
from sim.registry import WELLS
from sim.scada import query_series

METRICS_BY_TYPE: dict[str, list[str]] = {
    "oil": ["pump_efficiency", "submergence", "current", "daily_oil_prod", "casing_pressure"],
    "gas": ["daily_gas_prod", "wellhead_pressure", "throttle_in_pressure", "wellhead_temp"],
    "drilling": ["wob", "rpm", "mud_density"],
}


def key_metrics(well_id: str, start: str, end: str) -> list[TelemetryResult]:
    """按井型拉取该井的关键指标时序。"""
    well = WELLS.get(well_id)
    if not well:
        return []
    out: list[TelemetryResult] = []
    for suffix in METRICS_BY_TYPE.get(well.well_type, []):
        spec = spec_by_suffix(suffix)
        if spec:
            out.append(query_series(tag_for(spec, well_id), start, end))
    return out


def trend_word(t: TelemetryResult) -> str:
    """趋势判定（确定性）：下行 / 上行 / 平稳 / 数据不足。"""
    if len(t.series) < 2:
        return "数据不足"
    a, b = t.series[0].value, t.series[-1].value
    rel = (b - a) / abs(a) if a else 0.0
    if rel <= -0.1:
        return "下行"
    if rel >= 0.1:
        return "上行"
    return "平稳"


def digest(t: TelemetryResult) -> str:
    """把一条时序压成单行摘要，供 LLM 提示词使用。"""
    if not t.series:
        return f"{t.metric}({t.tag}): 无数据"
    a, b = t.series[0].value, t.series[-1].value
    unit = f" {t.unit}" if t.unit and t.unit != "1" else ""
    tail = ""
    if t.quality.get("gap"):
        tail = f"；数据缺口 {';'.join(t.quality['gap'])}"
    return f"{t.metric}: {a}{unit}→{b}{unit}（{trend_word(t)}）{tail}"
