"""端到端编排链路测试（mock LLM + sim 数据源）。"""

import pytest

from apps.orchestrator import build_orchestrator
from libs.llm import MockLLMClient
from libs.schemas import AgentName


@pytest.fixture
def orch():
    return build_orchestrator(MockLLMClient(delay=0))


def _agents(final):
    return {r.agent for r in final.results}


async def test_clarify_on_ambiguous_caliber(orch):
    """「产量」有多口径 → 必须澄清，不得猜测。"""
    final = await orch.run("3号井今天的产量是多少？", "s1")
    assert final.need_clarify
    assert any("口径" in o for o in final.clarify_options)
    assert final.results == []


async def test_clarify_on_vague_time(orch):
    """「上周」有歧义 → 必须追问。"""
    final = await orch.run("3号井上周的井口日产量是多少？", "s1")
    assert final.need_clarify
    assert final.results == []


async def test_clarify_on_unknown_well(orch):
    """不存在的井 → 给出候选，禁止编造。"""
    final = await orch.run("W-9今天的井口日产量是多少？", "s1")
    assert final.need_clarify
    assert final.clarify_options


async def test_production_query_full_chain(orch):
    final = await orch.run("3号井今天的井口日产量是多少？", "s1")
    assert not final.need_clarify
    assert AgentName.DATA_COLLECTOR in _agents(final)
    assert AgentName.PRODUCTION_ANALYSIS in _agents(final)
    assert final.citations
    assert final.trace_id.startswith("tr-")


async def test_diagnosis_supply_insufficiency_and_review(orch):
    final = await orch.run("3号井今天设备有什么故障？", "s1")
    assert AgentName.DEVICE_DIAGNOSIS in _agents(final)
    assert "供液不足" in final.answer
    # needs_review → 追加生产分析复核子任务
    assert AgentName.PRODUCTION_ANALYSIS in _agents(final)
    # 证据来自 sim（沉没度 / 泵效）
    assert any(e.metric in ("沉没度", "泵效") for r in final.results for e in r.evidence)


async def test_diagnosis_known_event_not_fault(orch):
    """事件日历命中「检修」→ 不得误判为设备故障。"""
    final = await orch.run("W-1今天设备有什么故障？", "s1")
    assert "人工事件" in final.answer or "检修" in final.answer
    assert "供液不足" not in final.answer


async def test_risk_h2s_triggers_alert_handler(orch):
    final = await orch.run("W-7井口有没有硫化氢风险？", "s1")
    assert AgentName.SAFETY_RISK in _agents(final)
    assert AgentName.ENVIRONMENT_SAFETY in _agents(final)
    assert AgentName.VIDEO_INTELLIGENCE in _agents(final)
    assert AgentName.ALERT_HANDLER in _agents(final)  # 预警 → 自动派生告警
    assert "预警" in final.answer


async def test_knowledge_rag_with_source_refs(orch):
    final = await orch.run("抽油机供液不足怎么处理？", "s1")
    assert AgentName.REPORT_KNOWLEDGE in _agents(final)
    assert any("规程" in c or "案例" in c or "预案" in c for c in final.citations)


async def test_knowledge_not_found_is_honest(orch):
    final = await orch.run("火箭发动机怎么维护？", "s1")
    assert "知识库中暂无" in final.answer


async def test_report_generation(orch):
    final = await orch.run("生成3号井今天的班报", "s1")
    assert AgentName.REPORT_KNOWLEDGE in _agents(final)
    assert "班报" in final.answer


async def test_general_no_dispatch(orch):
    final = await orch.run("你好", "s1")
    assert final.results == []
    assert "值班助手" in final.answer


async def test_budget_limit_and_no_circular(orch):
    """多意图 + 告警派生：受 5 次调用预算约束，且不出现循环。"""
    final = await orch.run("W-7有没有硫化氢隐患，产量下降原因是什么？", "s1")
    assert len(final.results) <= 5
    assert not any("循环" in c for c in final.conflicts)


async def test_all_results_have_timing_or_error(orch):
    final = await orch.run("3号井今天的井口日产量是多少？", "s1")
    for r in final.results:
        assert r.elapsed_ms is not None or r.error
