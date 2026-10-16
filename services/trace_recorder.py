"""链路记录服务：编排器每完成一次请求即全量落库，供追踪页回溯。"""

from __future__ import annotations

import structlog

from libs.schemas import FinalAnswer, StructuredIntent
from libs.schemas.trace import TraceRecord
from repositories.trace_repo import TraceRepository

logger = structlog.get_logger(__name__)


class TraceRecorder:
    """把一次请求的意图、节点结论、冲突、耗时写入仓储。"""

    def __init__(self, repo: TraceRepository) -> None:
        self._repo = repo

    async def record(
        self,
        question: str,
        intent: StructuredIntent,
        final: FinalAnswer,
        duration_ms: int,
    ) -> None:
        record = TraceRecord(
            trace_id=final.trace_id or intent.trace_id,
            session_id=final.session_id,
            question=question,
            intent=intent.intent.value,
            need_clarify=intent.need_clarify,
            agents=[r.agent.value for r in final.results],
            results=final.results,
            conflicts=final.conflicts,
            partial=final.partial,
            duration_ms=duration_ms,
        )
        await self._repo.save(record)
        logger.info(
            "trace.recorded",
            trace_id=record.trace_id,
            intent=record.intent,
            agents=len(record.agents),
            duration_ms=duration_ms,
        )
