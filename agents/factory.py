"""Agent 工厂：按依赖注入 LLM 客户端构建 8 个可编排节点。"""

from __future__ import annotations

from libs.llm.base import LLMClient
from libs.schemas import AgentName
from services.alert_service import AlertService
from services.kb_service import KBService

from agents.alert_handler import AlertHandlerAgent
from agents.base import BaseAgent
from agents.data_collector import DataCollectorAgent
from agents.device_diagnosis import DeviceDiagnosisAgent
from agents.environment_safety import EnvironmentSafetyAgent
from agents.production_analysis import ProductionAnalysisAgent
from agents.report_knowledge import ReportKnowledgeAgent
from agents.safety_risk import SafetyRiskAgent
from agents.video_intelligence import VideoIntelligenceAgent


def build_agents(llm: LLMClient,
                 alert_service: AlertService | None = None,
                 kb_service: KBService | None = None) -> dict[AgentName, BaseAgent]:
    """构建 8 个可编排节点（值班助手与调度器由编排层单独持有）。

    alert_service / kb_service 缺省时构建独立实例或回退 sim（测试场景）；
    生产由容器注入，保证处置/检索与 API 查询同源。
    """
    if alert_service is None:  # pragma: no cover - 仅兜底，正常路径由容器注入
        from repositories.alert_repo import AlertRepository, WorkOrderRepository

        alert_service = AlertService(AlertRepository(), WorkOrderRepository())
    return {
        AgentName.DATA_COLLECTOR: DataCollectorAgent(),
        AgentName.VIDEO_INTELLIGENCE: VideoIntelligenceAgent(),
        AgentName.ENVIRONMENT_SAFETY: EnvironmentSafetyAgent(),
        AgentName.DEVICE_DIAGNOSIS: DeviceDiagnosisAgent(llm),
        AgentName.PRODUCTION_ANALYSIS: ProductionAnalysisAgent(llm),
        AgentName.SAFETY_RISK: SafetyRiskAgent(llm),
        AgentName.REPORT_KNOWLEDGE: ReportKnowledgeAgent(llm, kb_service),
        AgentName.ALERT_HANDLER: AlertHandlerAgent(alert_service),
    }
