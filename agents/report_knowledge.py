"""报表知识 Agent（执行层 · LLM Agent，提示词 3.10）。

职责：班报/日报/月报生成 + 规程知识问答（RAG）。
知识问答只依据检索到的条目回答，必须附 source_refs；检索不到明确说明。
"""

from __future__ import annotations

from agents._helpers import digest, key_metrics
from agents.base import BaseAgent
from libs.llm.base import LLMClient, LLMMessage
from libs.prompts import REPORT_KNOWLEDGE, build_system_prompt
from libs.schemas import (
    AgentName,
    AgentResult,
    AgentTask,
    ReportKnowledgeOutput,
)
from services.kb_service import KBService

_ROLE = "报表知识"


class ReportKnowledgeAgent(BaseAgent):
    name = AgentName.REPORT_KNOWLEDGE

    def __init__(self, llm: LLMClient, kb_service: KBService | None = None) -> None:
        self._llm = llm
        self._kb = kb_service

    async def _search(self, question: str, top_k: int = 3) -> list[dict]:
        """统一知识检索：容器注入 KBService 时走知识库；缺省回退 sim（测试兼容）。"""
        if self._kb is not None:
            return await self._kb.search(question, top_k=top_k)
        from sim.knowledge import search_knowledge

        return search_knowledge(question, top_k=top_k)

    async def _process(self, task: AgentTask) -> AgentResult:
        kind = task.payload.get("kind", "knowledge")
        question = task.payload.get("question", "")
        well = task.payload.get("well", "")
        start, end = (task.payload.get("time_range") or ["", ""])[:2]

        if kind == "report":
            return await self._build_report(well, start, end, task)

        entries = await self._search(question, top_k=3)
        if not entries:
            return AgentResult(
                agent=self.name, trace_id=task.trace_id,
                conclusion="知识库中暂无此内容，建议联系工艺负责人补充",
                confidence=0.4, needs_review=False,
            )

        kb_text = "\n".join(f"[{e['source_ref']}] {e['text']}" for e in entries)
        out: ReportKnowledgeOutput = await self._llm.chat_with_json(
            messages=[
                LLMMessage(role="system", content=build_system_prompt(_ROLE, REPORT_KNOWLEDGE)),
                LLMMessage(role="user", content=f"问题：{question}\n检索到的知识条目：\n{kb_text}"),
            ],
            response_model=ReportKnowledgeOutput,
        )
        refs = [e["source_ref"] for e in entries]
        return AgentResult(
            agent=self.name, trace_id=task.trace_id,
            conclusion=out.answer, confidence=0.85,
            evidence=[],
            suggestion="涉及安全处置请以现场应急预案为准",
            citations=refs,
            data={"source_refs": refs, "knowledge_ids": [e["id"] for e in entries]},
        )

    async def _build_report(self, well: str, start: str, end: str, task: AgentTask) -> AgentResult:
        if not well:
            return AgentResult(agent=self.name, trace_id=task.trace_id,
                               conclusion="生成报表需指定井号", confidence=0.4)
        metrics = key_metrics(well, start, end)
        lines: list[str] = []
        gap_note: list[str] = []
        for t in metrics:
            if not t.series:
                continue
            last = t.series[-1]
            unit = t.unit if t.unit != "1" else ""
            lines.append(f"- {t.metric}：{last.value} {unit}".rstrip())
            if t.quality.get("gap"):
                gap_note.append(f"{t.metric} {';'.join(t.quality['gap'])}")
        report = f"【{well} 生产班报】{start} ~ {end}\n" + "\n".join(lines)
        if gap_note:
            report += "\n缺数时段：" + "；".join(gap_note)
        return AgentResult(
            agent=self.name, trace_id=task.trace_id,
            conclusion=f"已生成 {well} 生产班报", confidence=0.95,
            evidence=[],
            citations=[f"TDengine {t.tag} {start}~{end}" for t in metrics],
            data={"report": report},
        )
