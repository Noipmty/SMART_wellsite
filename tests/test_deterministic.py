"""确定性组件测试：时间解析 / 实体校验 / 引用绑定 / 告警去重。"""

from datetime import datetime, timedelta

from libs.deterministic import (
    AlertDeduplicator,
    EntityValidator,
    bind_citations,
    parse_time,
)
from libs.schemas import Entities

_NOW = datetime(2026, 10, 16, 10, 0)


def test_parse_time_vague_is_ambiguous():
    for q in ["上周", "最近", "那天"]:
        r = parse_time(q, now=_NOW)
        assert r.ambiguous and r.range is None


def test_parse_time_concrete():
    r = parse_time("昨天", now=_NOW)
    assert r.range == ["2026-10-15 00:00", "2026-10-15 23:59"]
    r = parse_time("2026-10-14", now=_NOW)
    assert r.range == ["2026-10-14 00:00", "2026-10-14 23:59"]
    r = parse_time("近3天", now=_NOW)
    assert r.range is not None and len(r.range) == 2


def test_validator_ok_case():
    v = EntityValidator().validate(
        Entities(well="3号井", metric="井口日产量", time=["2026-10-16 00:00", "2026-10-16 23:59"]),
        now=_NOW,
    )
    assert v.ok and not v.need_clarify
    assert v.well_id == "W-3" and v.tag == "W3.daily_oil_prod"


def test_validator_ambiguous_caliber():
    v = EntityValidator().validate(Entities(well="W-3", metric="产量"), now=_NOW)
    assert v.need_clarify
    assert any("口径" in o for o in v.clarify_options)


def test_validator_unknown_well_gives_candidates():
    v = EntityValidator().validate(Entities(well="W-9", metric="井口日产量"), now=_NOW)
    assert v.need_clarify
    assert v.clarify_options


def test_validator_gap_mismatch():
    v = EntityValidator().validate(Entities(well="W-3", metric="日产气量"), now=_NOW)
    assert v.need_clarify  # 采油井没有气量指标


def test_dedup_window_and_escalation():
    d = AlertDeduplicator(window_minutes=10)
    t0 = datetime(2026, 10, 16, 10, 0)
    a = d.aggregate("env_monitor", "H2S 超阈值", "预警", "W-7", now=t0)
    assert a.is_new and a.count == 1
    b = d.aggregate("env_monitor", "H2S 超阈值", "预警", "W-7", now=t0 + timedelta(minutes=1))
    assert not b.is_new and b.suppressed
    c = d.aggregate("env_monitor", "H2S 超阈值", "紧急", "W-7", now=t0 + timedelta(minutes=2))
    assert c.escalated
    e = d.aggregate("env_monitor", "H2S 超阈值", "预警", "W-7", now=t0 + timedelta(minutes=30))
    assert e.is_new  # 超出窗口重新计数


def test_citation_binding_rejects_unknown():
    allowed = ["TDengine W3.daily_oil_prod", "W-3 供液不足案例（2026-05）"]
    valid, rejected = bind_citations(
        ["TDengine W3.daily_oil_prod", "记忆里的无关数据"], allowed
    )
    assert valid == ["TDengine W3.daily_oil_prod"]
    assert rejected == ["记忆里的无关数据"]
