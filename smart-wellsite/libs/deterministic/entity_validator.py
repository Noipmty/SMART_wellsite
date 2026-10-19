"""实体校验器：井号 / 点表 / 时间交叉匹配，命中不到即反问。

对应提示词"实体先校验再查询"与"禁止猜测"。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from libs.schemas import Entities
from sim.points import PointSpec, resolve_metric, tag_for
from sim.registry import WELLS, candidate_wells, normalize_well
from libs.deterministic.timeparse import parse_time


@dataclass
class ValidationResult:
    ok: bool = False
    need_clarify: bool = False
    well_id: str | None = None
    spec: PointSpec | None = None
    tag: str | None = None
    time_range: list[str] | None = None
    clarify_options: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


class EntityValidator:
    """对值班助手抽取的实体做确定性校验。"""

    def validate(self, entities: Entities, now: datetime | None = None) -> ValidationResult:
        res = ValidationResult()

        # 1. 井号
        if entities.well:
            well_id = normalize_well(entities.well)
            if well_id is None:
                res.need_clarify = True
                cands = candidate_wells(entities.well)
                res.clarify_options = cands[:5]
                res.messages.append(f"系统中未找到井“{entities.well}”，请从候选中选择：{', '.join(cands)}")
                return res
            res.well_id = well_id
        else:
            res.need_clarify = True
            res.clarify_options = list(WELLS.keys())
            res.messages.append("未识别到井号，请指定具体井（如 W-3）")
            return res

        well = WELLS[res.well_id]

        # 2. 指标 → 点表语义
        if entities.metric:
            specs = resolve_metric(entities.metric, well.well_type)
            if not specs:
                res.need_clarify = True
                res.messages.append(
                    f"{res.well_id}（{well.well_type}）未找到指标“{entities.metric}”，请确认指标名"
                )
                return res
            if len(specs) > 1:
                res.need_clarify = True
                res.clarify_options = [f"{sp.metric}（口径：{sp.caliber}）" for sp in specs]
                res.messages.append(
                    f"指标“{entities.metric}”存在多个口径，请确认："
                    + "；".join(res.clarify_options)
                )
                return res
            res.spec = specs[0]
            res.tag = tag_for(specs[0], res.well_id)

        # 3. 时间
        if entities.time and len(entities.time) >= 2:
            res.time_range = [entities.time[0], entities.time[1]]
        else:
            tp = parse_time(entities.time[0] if entities.time else None, now=now)
            if tp.ambiguous:
                res.need_clarify = True
                res.messages.append(tp.reason)
                return res
            res.time_range = tp.range

        res.ok = True
        return res
