"""领域枚举：意图类型、Agent 名称、风险/告警等级、置信度。"""

from __future__ import annotations

from enum import Enum


class IntentType(str, Enum):
    """值班助手识别出的意图类型（可多选）。"""

    PRODUCTION_QUERY = "production_query"      # 生产数据查询
    PRODUCTION_ANALYSIS = "production_analysis"  # 工况/产量/参数优化分析
    DIAGNOSIS = "diagnosis"                    # 设备诊断
    RISK = "risk"                              # 安全咨询 / 风险分级
    REPORT = "report"                          # 报表（班报/日报/月报）
    KNOWLEDGE = "knowledge"                    # 规程与案例问答（RAG）
    GENERAL = "general"                        # 通用问题（不派发 Agent）


class AgentName(str, Enum):
    """系统中 10 个节点。"""

    # 交互层
    DUTY_ASSISTANT = "duty_assistant"
    # 编排层
    ORCHESTRATOR = "orchestrator"
    # 感知层
    DATA_COLLECTOR = "data_collector"
    VIDEO_INTELLIGENCE = "video_intelligence"
    ENVIRONMENT_SAFETY = "environment_safety"
    # 分析层
    DEVICE_DIAGNOSIS = "device_diagnosis"
    PRODUCTION_ANALYSIS = "production_analysis"
    SAFETY_RISK = "safety_risk"
    # 执行层
    ALERT_HANDLER = "alert_handler"
    REPORT_KNOWLEDGE = "report_knowledge"


# LLM 决策 Agent（6 个：system prompt）
LLM_AGENTS: set[AgentName] = {
    AgentName.DUTY_ASSISTANT,
    AgentName.ORCHESTRATOR,
    AgentName.DEVICE_DIAGNOSIS,
    AgentName.PRODUCTION_ANALYSIS,
    AgentName.SAFETY_RISK,
    AgentName.REPORT_KNOWLEDGE,
}

# 确定性节点（4 个：职责规则）
DETERMINISTIC_AGENTS: set[AgentName] = {
    AgentName.DATA_COLLECTOR,
    AgentName.VIDEO_INTELLIGENCE,
    AgentName.ENVIRONMENT_SAFETY,
    AgentName.ALERT_HANDLER,
}


class Level(str, Enum):
    """告警 / 风险等级（中文，按现场规程分级）。"""

    INFO = "提示"
    WATCH = "提醒"
    WARNING = "预警"
    CRITICAL = "紧急"


class ConfidenceLevel(str, Enum):
    """结论置信度。"""

    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


def to_confidence_level(score: float) -> ConfidenceLevel:
    """将 0~1 的置信度分值映射为 高/中/低。"""
    if score >= 0.8:
        return ConfidenceLevel.HIGH
    if score >= 0.6:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW
