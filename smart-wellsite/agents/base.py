"""Agent 基类：统一 handle(task) -> AgentResult 接口。

所有节点（LLM Agent 与确定性节点）都实现该接口，编排器据此统一调度、聚合。
"""

from __future__ import annotations

import abc
import time

from libs.schemas import AgentName, AgentResult, AgentTask


class BaseAgent(abc.ABC):
    """Agent 抽象基类。"""

    name: AgentName

    async def handle(self, task: AgentTask) -> AgentResult:
        """统一入口：包裹异常、记录耗时。"""
        start = time.monotonic()
        try:
            result = await self._process(task)
        except Exception as exc:  # noqa: BLE001 - 统一降级为 partial 结果
            result = AgentResult(
                agent=self.name,
                trace_id=task.trace_id,
                task_id=task.task_id,
                conclusion="处理失败",
                error=f"{type(exc).__name__}: {exc}",
                partial=True,
            )
        result.elapsed_ms = int((time.monotonic() - start) * 1000)
        result.task_id = result.task_id or task.task_id
        return result

    @abc.abstractmethod
    async def _process(self, task: AgentTask) -> AgentResult:
        """子类实现具体的处理逻辑。"""
        raise NotImplementedError
