"""知识与案例库（RAG mock）。

报表知识 Agent 只依据检索到的条目回答，必须附 source_refs。
"""

from __future__ import annotations

KB_ENTRIES: list[dict] = [
    {
        "id": "KB-OPS-001",
        "source_ref": "《抽油机操作规程》第 3.2 节",
        "type": "规程",
        "title": "抽油机冲次调整",
        "text": "当出现供液不足（泵效下降、沉没度下降、产量下降）时，应按 0.5~1 次/min 步长调低冲次，"
                "调整后至少观察 4 小时，待动液面恢复后再逐步回调。",
        "tags": ["冲次", "泵效", "沉没度", "供液不足", "抽油机"],
    },
    {
        "id": "KB-EMG-001",
        "source_ref": "《井场应急预案》第 2 章 硫化氢防护",
        "type": "预案",
        "title": "H2S 泄漏应急处置",
        "text": "H2S 达到预警值（10ppm）时，应安排人员佩戴检测仪上风向接近确认，暂停周边动火作业；"
                "达到紧急值（20ppm）时，立即通知值班班长，人员撤离至上风向集合点并启动应急联动。",
        "tags": ["H2S", "气体", "应急", "预案", "撤离", "动火"],
    },
    {
        "id": "KB-CASE-001",
        "source_ref": "W-3 供液不足案例（2026-05）",
        "type": "案例",
        "title": "W-3 供液不足处置案例",
        "text": "2026-05 W-3 出现泵效由 0.45 降至 0.30、沉没度由 320m 降至 120m，判断为供液不足，"
                "将冲次由 6 次/min 调至 4 次/min，观察 8 小时后泵效恢复至 0.41。",
        "tags": ["供液不足", "泵效", "沉没度", "W-3", "冲次", "案例"],
    },
    {
        "id": "KB-OPS-002",
        "source_ref": "《采气井生产管理规定》第 4.1 节",
        "type": "规程",
        "title": "采气井节流与结蜡",
        "text": "采气井应关注节流前压力与水合物、结蜡特征。节流前压力持续升高且产量下降时，"
                "应排查节流阀结冰或水合物堵塞。",
        "tags": ["节流", "水合物", "结蜡", "采气", "压力"],
    },
    {
        "id": "KB-DRL-001",
        "source_ref": "《钻井作业规程》第 5 章",
        "type": "规程",
        "title": "钻井参数监控",
        "text": "钻井过程应连续监控钻压、转速与泥浆密度。泥浆密度突降或转速异常波动时，"
                "应警惕井涌风险，立即降低钻压并循环观察。",
        "tags": ["钻压", "转速", "泥浆密度", "井涌", "钻井"],
    },
]


def search_knowledge(query: str, top_k: int = 3) -> list[dict]:
    """按关键词重合度检索知识条目（mock RAG）。"""
    if not query:
        return []
    q = str(query)
    scored: list[tuple[int, dict]] = []
    for entry in KB_ENTRIES:
        score = 0
        for tag in entry["tags"]:
            if tag in q:
                score += 2
        if entry["title"] in q:
            score += 3
        for ch in set(q):
            if len(ch.strip()) and ch in entry["text"]:
                score += 1
        if score > 0:
            scored.append((score, entry))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:top_k]]
