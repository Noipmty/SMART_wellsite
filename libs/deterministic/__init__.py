"""确定性组件包：时间解析 / 实体校验 / 引用绑定 / 告警去重 / 本地兜底。"""

from libs.deterministic.citation import allowed_from_query, bind_citations
from libs.deterministic.dedup import AlertDeduplicator, DedupOutcome
from libs.deterministic.entity_validator import EntityValidator, ValidationResult
from libs.deterministic.fallback import (
    detect_series_anomaly,
    fallback_answer,
    is_llm_unavailable_error,
    threshold_check,
)
from libs.deterministic.timeparse import TimeParseResult, parse_time

__all__ = [
    "parse_time",
    "TimeParseResult",
    "EntityValidator",
    "ValidationResult",
    "bind_citations",
    "allowed_from_query",
    "AlertDeduplicator",
    "DedupOutcome",
    "detect_series_anomaly",
    "threshold_check",
    "fallback_answer",
    "is_llm_unavailable_error",
]
