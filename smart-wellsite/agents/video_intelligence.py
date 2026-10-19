"""视频智能 Agent（感知层 · 模型 + 可选 LLM）。

职责：RTSP 流 / 关键帧智能识别；高风险事件（烟火、闯入）多帧多视角二次确认后才发布，降误报。
"""

from __future__ import annotations

from agents.base import BaseAgent
from libs.schemas import AgentName, AgentResult, AgentTask, Evidence
from sim.env_video import describe_frame, query_video

HIGH_RISK = {"烟火", "油气泄漏", "违规闯入"}
MIN_FRAMES = 3  # 高风险事件连续命中帧数下限


class VideoIntelligenceAgent(BaseAgent):
    name = AgentName.VIDEO_INTELLIGENCE

    async def _process(self, task: AgentTask) -> AgentResult:
        well = task.payload.get("well")
        cam_id = task.payload.get("cam_id")
        tr = task.payload.get("time_range") or []
        start, end = (tr + ["", ""])[:2]

        raw = query_video(cam_id, well, start, end)

        evidence: list[Evidence] = []
        confirmed: list[dict] = []
        for ev in raw:
            high = ev["class"] in HIGH_RISK
            ok = (not high) or (ev["frames"] >= MIN_FRAMES and ev["perspectives"] >= 1)
            if ok:
                confirmed.append(ev)
                evidence.append(
                    Evidence(
                        ts=ev["ts"],
                        metric=ev["class"],
                        value=round(ev["conf"], 2),
                        source=f"video {ev['cam_id']}",
                        detail=f"{describe_frame(ev)}（多帧二次确认 frames={ev['frames']}）",
                    )
                )

        conclusion = (
            f"识别到 {len(confirmed)} 条视频事件：" + "、".join(f"{e['class']}@{e['cam_id']}" for e in confirmed)
            if confirmed
            else "未识别到视频风险事件"
        )
        return AgentResult(
            agent=self.name,
            trace_id=task.trace_id,
            conclusion=conclusion,
            confidence=0.9 if confirmed else 1.0,
            evidence=evidence,
            needs_review=any(e["class"] in HIGH_RISK for e in confirmed),
            data={"detections": confirmed},
            citations=[f"video {e['cam_id']} {e['ts']}" for e in confirmed],
        )
