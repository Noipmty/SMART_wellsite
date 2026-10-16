"""点表语义映射表（Point Table Semantic Map）—— mock 数据源。

统一将用户口语化指标名映射到规范指标 + tag + 口径 + 单位。
"产量" 这类多口径指标会解析出多个候选，触发值班助手澄清（禁止猜测）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PointSpec:
    metric: str            # 规范指标名（含口径限定）
    tag_suffix: str        # tag 后缀，如 daily_oil_prod
    unit: str
    well_types: tuple[str, ...]
    aliases: tuple[str, ...]
    caliber: str           # 口径说明（如 井口产量 / 净化产量）
    is_primary: bool = False  # 同义指标中的首选口径


POINTS: list[PointSpec] = [
    # ---------- 采油井 ----------
    PointSpec("井口日产量", "daily_oil_prod", "t/d", ("oil",),
              ("井口产量", "井口日产量", "日产量", "产油量", "产量", "出油量"),
              "井口产量", is_primary=True),
    PointSpec("净化日产量", "daily_oil_clean", "t/d", ("oil",),
              ("净化产量", "外输产量", "净化日产量", "外输量", "产量"),
              "净化产量"),
    PointSpec("泵效", "pump_efficiency", "1", ("oil",),
              ("泵效", "泵效率", "泵排量效率"), "抽油泵效"),
    PointSpec("沉没度", "submergence", "m", ("oil",),
              ("沉没度", "动液面", "液面深度", "沉没度深度"), "泵挂沉没度"),
    PointSpec("电流", "current", "A", ("oil",),
              ("电流", "上行电流", "电机电流"), "抽油机上行电流"),
    PointSpec("套压", "casing_pressure", "MPa", ("oil",),
              ("套压", "套管压力", "套管压"), "井口套管压力"),
    PointSpec("冲次", "stroke_freq", "次/min", ("oil",),
              ("冲次", "冲程次数", "冲数"), "抽油机冲次"),
    # ---------- 采气井 ----------
    PointSpec("日产气量", "daily_gas_prod", "10^4 m3/d", ("gas",),
              ("日产气量", "产气量", "气量", "产量", "出气量"),
              "井口日产气量", is_primary=True),
    PointSpec("井口压力", "wellhead_pressure", "MPa", ("gas",),
              ("井口压力", "井口油压", "油压"), "井口回压"),
    PointSpec("节流前压力", "throttle_in_pressure", "MPa", ("gas",),
              ("节流前压力", "节流压力", "上游压力"), "节流阀前压力"),
    PointSpec("井口温度", "wellhead_temp", "℃", ("gas",),
              ("井口温度", "温度", "出气温度"), "井口温度"),
    # ---------- 钻井 ----------
    PointSpec("钻压", "wob", "kN", ("drilling",),
              ("钻压", "钻头压力"), "钻头钻压"),
    PointSpec("转速", "rpm", "r/min", ("drilling",),
              ("转速", "转盘转速", "钻速"), "转盘转速"),
    PointSpec("泥浆密度", "mud_density", "g/cm3", ("drilling",),
              ("泥浆密度", "钻井液密度", "泥浆比重"), "钻井液密度"),
]

# 便捷索引：suffix → spec
_BY_SUFFIX: dict[str, PointSpec] = {p.tag_suffix: p for p in POINTS}


def spec_by_suffix(suffix: str) -> PointSpec | None:
    """按 tag 后缀取点表规格。"""
    return _BY_SUFFIX.get(suffix)


def resolve_metric(alias: str | None, well_type: str | None = None) -> list[PointSpec]:
    """把用户指标名解析为候选点表规格列表。

    - 返回空列表：系统中未找到该指标
    - 返回 1 个：唯一口径
    - 返回多个：口径歧义，需澄清（如 "产量"）
    """
    if not alias:
        return []
    key = str(alias).strip()
    hits: list[PointSpec] = []
    for p in POINTS:
        if well_type and well_type not in p.well_types:
            continue
        if key == p.metric or any(key == a for a in p.aliases):
            hits.append(p)
    if hits:
        return hits
    # 模糊包含匹配（如 "日产量" 包含于 "井口日产量"）
    for p in POINTS:
        if well_type and well_type not in p.well_types:
            continue
        if key in p.metric or any(key in a for a in p.aliases):
            hits.append(p)
    return hits


def tag_for(spec: PointSpec, well_id: str) -> str:
    """构造规范 tag，如 W-3 + daily_oil_prod → W3.daily_oil_prod。"""
    return f"{well_id.replace('-', '').replace('_', '')}.{spec.tag_suffix}"


def split_tag(tag: str) -> tuple[str, str]:
    """拆分 tag 为 (well_id, suffix)。返回 ("", "") 表示无法解析。"""
    if "." not in tag:
        return "", ""
    head, suffix = tag.split(".", 1)
    num = "".join(ch for ch in head if ch.isdigit())
    well_id = f"W-{num}" if num else head
    return well_id, suffix
