"""编排层包：把 10 个节点组装成可运行的请求链路。"""

from agents.duty_assistant import DutyAssistantAgent
from agents.factory import build_agents
from apps.orchestrator.engine import Orchestrator
from libs.llm.base import LLMClient
from services.alert_service import AlertService
from services.kb_service import KBService
from services.trace_recorder import TraceRecorder


def build_orchestrator(llm: LLMClient,
                       trace_recorder: TraceRecorder | None = None,
                       alert_service: AlertService | None = None,
                       kb_service: KBService | None = None) -> Orchestrator:
    """装配编排器：值班助手 + 8 个节点 + 调度路由规则 + 链路记录器。"""
    return Orchestrator(build_agents(llm, alert_service=alert_service,
                                     kb_service=kb_service),
                        DutyAssistantAgent(),
                        trace_recorder=trace_recorder)


__all__ = ["Orchestrator", "build_orchestrator"]
