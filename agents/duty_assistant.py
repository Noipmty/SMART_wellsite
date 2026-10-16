"""值班助手 Agent（交互层 · LLM Agent，提示词 3.1）。

职责：理解问题 → 抽取实体 → 必要时澄清 → 生成结构化意图 → 组织最终回答。
实体校验由确定性 EntityValidator 完成（禁止猜测）；最终回答由本 Agent 合成。
"""

from __future__ import annotations

import re
from datetime import datetime

from libs.deterministic import EntityValidator, bind_citations, parse_time
from libs.schemas import (
    AgentResult,
    ConfidenceLevel,
    Entities,
    FinalAnswer,
    IntentType,
    StructuredIntent,
    to_confidence_level,
)
from sim.points import POINTS
from sim.registry import normalize_well

_WELL_RE = re.compile(r"(?:W|w)[-_\s]?\d+|\d+\s*号(?:井|采油井|采气井|钻井)?")

# 需要井号的意图（知识问答 / 通用问题不需要）
_NEEDS_WELL = {
    IntentType.PRODUCTION_QUERY,
    IntentType.PRODUCTION_ANALYSIS,
    IntentType.DIAGNOSIS,
    IntentType.RISK,
    IntentType.REPORT,
}

# 意图优先级（多意图时的主意图）
_PRIORITY = [
    IntentType.DIAGNOSIS,
    IntentType.RISK,
    IntentType.PRODUCTION_ANALYSIS,
    IntentType.PRODUCTION_QUERY,
    IntentType.REPORT,
    IntentType.KNOWLEDGE,
    IntentType.GENERAL,
]


def detect_intents(q: str) -> list[IntentType]:
    """规则化意图识别（可多选）。"""
    intents: list[IntentType] = []

    def has(*ks: str) -> bool:
        return any(k in q for k in ks)

    if has("为什么", "原因", "分析", "趋势", "优化"):
        intents.append(IntentType.PRODUCTION_ANALYSIS)
    if has("产量", "工况", "参数", "泵效", "沉没度", "电流", "压力", "温度",
           "钻压", "转速", "泥浆", "气量", "套压", "冲次"):
        intents.append(IntentType.PRODUCTION_QUERY)
    if has("诊断", "故障", "坏了", "不工作", "怎么回事", "异常", "问题"):
        intents.append(IntentType.DIAGNOSIS)
    if has("隐患", "安全", "风险", "气体", "H2S", "硫化氢", "报警", "告警", "泄漏", "闯入", "烟火"):
        intents.append(IntentType.RISK)
    if has("班报", "日报", "月报", "报表", "汇报"):
        intents.append(IntentType.REPORT)
    if has("规程", "什么是", "原理", "怎么处理", "预案", "案例", "规定", "标准",
           "维护", "保养", "如何", "规范", "方法", "要求"):
        intents.append(IntentType.KNOWLEDGE)
    return intents or [IntentType.GENERAL]


def _primary(intents: list[IntentType]) -> IntentType:
    for p in _PRIORITY:
        if p in intents:
            return p
    return IntentType.GENERAL


def _extract_well(q: str) -> str | None:
    m = _WELL_RE.search(q)
    if not m:
        return None
    raw = m.group(0)
    return normalize_well(raw) or raw  # 归一化失败时保留原文，交校验器报"未找到"


def _extract_metric(q: str) -> str | None:
    """取问题中命中的最长指标别名（越长越具体）。"""
    best = ""
    for p in POINTS:
        for a in p.aliases:
            if a in q and len(a) > len(best):
                best = a
    return best or None


class DutyAssistantAgent:
    """值班助手：不直接调用 LLM（NLU + 合成均确定性），LLM system prompt 见 libs.prompts.DUTY_ASSISTANT。"""

    def __init__(self) -> None:
        self._validator = EntityValidator()

    def understand(self, question: str, session_id: str | None = None,
                   now: datetime | None = None) -> StructuredIntent:
        """自然语言 → 结构化意图（含实体校验与澄清判定）。"""
        now = now or datetime.now()
        intents = detect_intents(question)
        primary = _primary(intents)

        well = _extract_well(question)
        metric = _extract_metric(question)
        tp = parse_time(question, now=now)
        vague_time = tp.ambiguous and "有歧义" in tp.reason
        time_range = tp.range
        if not time_range and not vague_time:
            # 未提供时间 → 默认今日全天
            today = now.strftime("%Y-%m-%d")
            time_range = [f"{today} 00:00", f"{today} 23:59"]

        entities = Entities(well=well, metric=metric, time=time_range,
                            raw={"intents": [i.value for i in intents]})

        need_clarify = False
        options: list[str] = []
        if primary in _NEEDS_WELL:
            vr = self._validator.validate(entities, now=now)
            need_clarify = vr.need_clarify or vague_time
            if vr.need_clarify:
                options = vr.clarify_options or ["请补充必要信息"]
            elif vague_time:
                options = ["请指定具体时间段，如「2026-10-14」或「今天」"]
        else:
            entities.well = None  # 知识问答 / 通用问题不绑定井号

        return StructuredIntent(
            intent=primary,
            entities=entities,
            confidence=0.85 if not need_clarify else 0.4,
            need_clarify=need_clarify,
            clarify_options=options,
            question=question,
            session_id=session_id,
        )

    def compose(self, question: str, intent: StructuredIntent,
                results: list[AgentResult], conflicts: list[str],
                trace_id: str, session_id: str | None) -> FinalAnswer:
        """把多 Agent 聚合结果组织成值班员可读的最终回答。"""
        if intent.need_clarify:
            return FinalAnswer(
                answer="需要先确认信息后才能查询：" + ("；".join(intent.clarify_options) or "请补充查询条件"),
                citations=[], need_clarify=True, clarify_options=intent.clarify_options,
                trace_id=trace_id, session_id=session_id,
            )

        conclusions: list[str] = []
        evidence_lines: list[str] = []
        suggestions: list[str] = []
        citations: list[str] = []
        report_text = ""

        if not results:
            return FinalAnswer(
                answer=("我是智慧井场值班助手，可协助查询生产数据、做设备诊断、评估安全风险、"
                        "生成班报/日报，或解答操作规程与案例问题。"
                        "例如：「3号井今天的井口日产量是多少？」「W-7 井口有没有硫化氢风险？」"),
                citations=[], trace_id=trace_id, session_id=session_id,
                confidence_level=ConfidenceLevel.LOW,
            )

        for r in results:
            if r.error:
                conclusions.append(f"{r.agent.value}：处理失败（{r.error}）")
                continue
            if r.conclusion:
                conclusions.append(f"{r.conclusion}（置信度 {r.confidence_level.value if r.confidence_level else '低'}）")
            for e in r.evidence[:4]:
                val = "" if e.value is None else f"={e.value}"
                tr = f"[{e.trend}]" if e.trend else ""
                ts = f"@{e.ts}" if e.ts else ""
                evidence_lines.append(f"{e.metric}{val}{tr}{ts}".strip())
            if r.suggestion:
                suggestions.append(r.suggestion)
            for pa in r.parameter_advice:
                suggestions.append(
                    f"{pa.param} {pa.from_value}→{pa.to_value}（{pa.reason}，需人工确认）"
                )
            citations.extend(r.citations)
            if r.data.get("report"):
                report_text = r.data["report"]

        answer = "【结论】" + ("；".join(conclusions) if conclusions else "暂无可给出的结论")
        if evidence_lines:
            answer += "\n【依据】" + "；".join(dict.fromkeys(evidence_lines))
        if conflicts:
            answer += "\n【分歧】" + "；".join(conflicts)
        if suggestions:
            answer += "\n【建议】" + "；".join(dict.fromkeys(suggestions))
        if report_text:
            answer += "\n" + report_text

        valid_citations, _rejected = bind_citations(list(dict.fromkeys(citations)), list(dict.fromkeys(citations)))

        conf = min((r.confidence for r in results), default=0.0)
        partial = any(r.partial or bool(r.error) for r in results)
        return FinalAnswer(
            answer=answer,
            citations=valid_citations,
            followup="可继续追问该井近 7 天趋势或相关规程",
            trace_id=trace_id,
            session_id=session_id,
            confidence_level=to_confidence_level(conf) if results else ConfidenceLevel.LOW,
            results=results,
            conflicts=conflicts,
            partial=partial,
        )
