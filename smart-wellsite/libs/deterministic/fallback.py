"""本地规则兜底：LLM/API 不可用时，异常检测与告警照常运行。

对应提示词"本地规则兜底 —— 降级不失效"。
"""

from __future__ import annotations

from libs.schemas import TelemetryResult
from sim.env_video import ENV_THRESHOLDS, level_for


def is_llm_unavailable_error(exc: Exception | None) -> bool:
    """判断异常是否属于 LLM 不可用（超时 / 连接 / 限流）。"""
    if exc is None:
        return False
    name = type(exc).__name__.lower()
    text = str(exc).lower()
    markers = ("timeout", "connect", "rate", "unavailable", "503", "502", "429", "notimplemented")
    return any(m in name or m in text for m in markers)


def detect_series_anomaly(telemetry: TelemetryResult, drop_ratio: float = 0.15) -> str | None:
    """确定性趋势异常检测（不依赖 LLM）。"""
    pts = telemetry.series
    if len(pts) < 2:
        return None
    first, last = pts[0].value, pts[-1].value
    if first == 0:
        return None
    change = (last - first) / abs(first)
    if change <= -drop_ratio:
        return f"{telemetry.metric} 较窗口初值下降 {abs(change) * 100:.1f}%"
    if change >= drop_ratio:
        return f"{telemetry.metric} 较窗口初值上升 {change * 100:.1f}%"
    return None


def threshold_check(metric: str, value: float) -> tuple[str | None, str]:
    """气体/环境阈值判定（确定性）。"""
    level = level_for(metric, value)
    th = ENV_THRESHOLDS.get(metric, {})
    detail = ""
    if th:
        detail = f"阈值 提醒{th['提醒']}/预警{th['预警']}/紧急{th['紧急']}"
    return level, detail


def fallback_answer(question: str) -> str:
    """LLM 不可用时的兜底回答（明确告知降级，不编造）。"""
    return (
        "【降级提示】当前智能问答服务不可用，已切换至本地规则模式。"
        "异常检测与告警链路不受影响，仍正常运行。"
        f"您的原始问题：{question}。请稍后重试，或直接联系值班班长。"
    )
