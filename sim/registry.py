"""井号表（Well Registry）—— mock 数据源。

真实部署时由 PostgreSQL devices 台账加载；此处内置 7 口井 + 1 套钻井设备，
覆盖采油 / 采气 / 钻井三种井型。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

SITE_ID = "WS001"

WELL_TYPE_CN: dict[str, str] = {"oil": "采油", "gas": "采气", "drilling": "钻井"}


@dataclass(frozen=True)
class Well:
    well_id: str
    name: str
    well_type: str  # oil / gas / drilling
    device_id: str
    device_type: str
    location: str
    status: str = "active"


WELLS: dict[str, Well] = {
    "W-1": Well("W-1", "1号采油井", "oil", "DEV-001", "pumping_unit", "东区 A 排"),
    "W-2": Well("W-2", "2号采气井", "gas", "DEV-002", "gas_wellhead", "东区 B 排"),
    "W-3": Well("W-3", "3号采油井", "oil", "DEV-003", "pumping_unit", "中区 C 排"),
    "W-4": Well("W-4", "4号钻井", "drilling", "DEV-004", "drilling_rig", "南区钻井平台"),
    "W-5": Well("W-5", "5号采油井", "oil", "DEV-005", "pumping_unit", "西区 D 排"),
    "W-6": Well("W-6", "6号采气井", "gas", "DEV-006", "gas_wellhead", "西区 E 排"),
    "W-7": Well("W-7", "7号采气井", "gas", "DEV-007", "gas_wellhead", "北区 F 排"),
}

# 井号别名表：用户可能输入 "3号井" / "W3" / "w-3" / "W_3" 等
_WELL_PATTERN = re.compile(r"(?:W|w)[-_\s]?(\d+)")
_CN_PATTERN = re.compile(r"(\d+)\s*号(?:井|采油井|采气井|钻井)?")


def normalize_well(text: str | None) -> str | None:
    """把用户输入归一化为规范井号（如 W-3），无法识别返回 None。"""
    if not text:
        return None
    s = str(text).strip().upper().replace(" ", "")
    m = _WELL_PATTERN.search(s)
    if m:
        candidate = f"W-{m.group(1)}"
        return candidate if candidate in WELLS else None
    # 中文 "3号井" → W-3
    m = _CN_PATTERN.search(str(text))
    if m:
        candidate = f"W-{m.group(1)}"
        return candidate if candidate in WELLS else None
    if s in WELLS:
        return s
    return None


def list_wells() -> list[Well]:
    """返回全部井。"""
    return list(WELLS.values())


def list_well_ids() -> list[str]:
    return list(WELLS.keys())


def candidate_wells(text: str) -> list[str]:
    """当输入模糊时，给出候选井列表（供值班助手澄清）。"""
    if not text:
        return list_well_ids()
    s = str(text)
    hits: list[str] = []
    for wid in WELLS:
        num = wid.split("-")[1]
        if num in s or wid in s.upper():
            hits.append(wid)
    return hits or list_well_ids()
