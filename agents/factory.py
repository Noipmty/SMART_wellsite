"""Agent 工厂：按依赖注入 LLM 客户端构建 8 个可编排节点。"""

from __future__ import annotations

from libs.llm.base import LLMClient
from libs.schemas import AgentName

from agents.alert_handler import AlertHandlerAgent
from agents.base import BaseAgent
from agents.data_collector import DataCollectorAgent
from agents.device_diagnosis import DeviceDiagnosisAgent
from agents.environment_safety import EnvironmentSafetyAgent
from agents.production_analysis import ProductionAnalysisAgent
from agents.report_knowledge import ReportKnowledgeAgent
from agents.safety_risk import SafetyRiskAgent
from agents.video_intelligence import VideoIntelligenceAgent


def build_agents(llm: LLMClient) -> dict[AgentName, BaseAgent]:
    """构建 8 个可编排节点（值班助手与调度器由编排层单独持有）。"""
    return {
        AgentName.DATA_COLLECTOR: DataCollectorAgent(),
        AgentName.VIDEO_INTELLIGENCE: VideoIntelligenceAgent(),
        AgentName.ENVIRONMENT_SAFETY: EnvironmentSafetyAgent(),
        AgentName.DEVICE_DIAGNOSIS: DeviceDiagnosisAgent(llm),
        AgentName.PRODUCTION_ANALYSIS: ProductionAnalysisAgent(llm),
        AgentName.SAFETY_RISK: SafetyRiskAgent(llm),
        AgentName.REPORT_KNOWLEDGE: ReportKnowledgeAgent(llm),
        AgentName.ALERT_HANDLER: AlertHandlerAgent(),
    }
