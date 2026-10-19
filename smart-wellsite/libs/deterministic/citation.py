"""引用绑定校验：回答引用必须来自本次查询/检索结果。

对应提示词"引用绑定校验"与"禁止引用记忆中的无关数据"。
"""

from __future__ import annotations


def bind_citations(citations: list[str], allowed_sources: list[str]) -> tuple[list[str], list[str]]:
    """校验引用来源合法性。

    Args:
        citations: 待校验的引用列表
        allowed_sources: 本次查询/检索允许的来源集合

    Returns:
        (合法引用, 被拒绝的引用)
    """
    allowed = {s.strip() for s in allowed_sources if s}
    valid: list[str] = []
    rejected: list[str] = []
    for c in citations:
        text = (c or "").strip()
        if not text:
            continue
        if _matches_any(text, allowed):
            valid.append(text)
        else:
            rejected.append(text)
    return valid, rejected


def _matches_any(text: str, allowed: set[str]) -> bool:
    if text in allowed:
        return True
    for a in allowed:
        if a and (a in text or text in a):
            return True
    return False


def allowed_from_query(tags: list[str], kb_refs: list[str], extra: list[str] | None = None) -> list[str]:
    """构造一次查询的允许来源集合。"""
    out: list[str] = []
    for t in tags:
        out.append(f"TDengine {t}")
    out.extend(kb_refs)
    out.extend(extra or [])
    return out
