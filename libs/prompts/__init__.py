"""提示词库：系统级共享前缀 + 6 个 LLM Agent 提示词 + 4 个确定性节点职责规则。"""

from libs.prompts.agents import (
    DEVICE_DIAGNOSIS,
    DUTY_ASSISTANT,
    ORCHESTRATOR,
    PRODUCTION_ANALYSIS,
    REPORT_KNOWLEDGE,
    SAFETY_RISK,
)
from libs.prompts.shared import SHARED_PREFIX, build_system_prompt

# 4 个确定性节点的职责规则（作为组件处理配置）
RULES_DATA_COLLECTOR = """【职责】数据采集 Agent：通过 OPC-UA/Modbus 对接 SCADA 点表按周期拉取 {tag,value,ts}；
数据质量治理（越限/跳变/重复/断档）并标记；断点续传补拉并标记"补数"；异常标记后发布标准化事件。
【规则】单位与口径以点表语义映射表为准，禁止猜测；数据缺口必须显式标注 gap，禁止静默填 0；
阈值/统计异常标记由确定性规则完成，不调用 LLM。"""

RULES_VIDEO = """【职责】视频智能 Agent：识别人员安全（未戴安全帽/未穿工服/违规闯入/跌倒）、环境风险（烟火/泄漏）、违规行为。
【规则】高风险事件（烟火、闯入）必须连续多帧/多视角二次确认后再发布以降误报；
发布事件须含 cam_id、时间、类别、置信度、关键帧引用；可选 LLM 描述必须基于画面事实，禁止脑补。"""

RULES_ENV = """【职责】环境安全 Agent：气体（H2S/可燃气体/CO）与气象（风速风向/温湿度/雨量/雷电）连续监测与预警。
【规则】分级阈值按现场安全规程配置（提醒/预警/紧急），达到阈值即发布事件；短时快速爬升即使未到阈值也发布"关注"；
大风/雷电预警联动告警处置 Agent 通知现场；传感器离线或数据异常 → 发布"数据缺失"事件，不得静默。"""

RULES_ALERT = """【职责】告警处置 Agent：告警分级、通知与工单闭环。
【规则】分级映射：提醒→记录+值班界面提示；预警→IM/短信通知值班员；紧急→电话+短信+声光并通知值班班长；
同源同因事件 10 分钟内聚合为一条；连续触发或等级提升时升级；
生成处置工单（含事件、建议、来源 trace_id），人工确认后更新状态；超时未处理自动升级；
旁路保障——本系统不可用时原有报警链路不受影响；所有通知内容附 trace_id 与置信度。"""

__all__ = [
    "SHARED_PREFIX",
    "build_system_prompt",
    "DUTY_ASSISTANT",
    "ORCHESTRATOR",
    "DEVICE_DIAGNOSIS",
    "PRODUCTION_ANALYSIS",
    "SAFETY_RISK",
    "REPORT_KNOWLEDGE",
    "RULES_DATA_COLLECTOR",
    "RULES_VIDEO",
    "RULES_ENV",
    "RULES_ALERT",
]
