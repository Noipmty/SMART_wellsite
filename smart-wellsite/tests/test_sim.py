"""sim 仿真数据源测试。"""

from sim.calendar import events_in_range, find_event
from sim.knowledge import search_knowledge
from sim.points import resolve_metric, spec_by_suffix, split_tag, tag_for
from sim.registry import candidate_wells, normalize_well
from sim.scada import query_series
from sim.timebase import DATE, at


def test_normalize_well_variants():
    assert normalize_well("3号井") == "W-3"
    assert normalize_well("W3") == "W-3"
    assert normalize_well("w-3") == "W-3"
    assert normalize_well("W_7") == "W-7"
    assert normalize_well("W-9") is None  # 不存在
    assert normalize_well("随便说") is None


def test_candidate_wells_when_unknown():
    assert "W-3" in candidate_wells("3")
    assert set(candidate_wells("")) == set(["W-1", "W-2", "W-3", "W-4", "W-5", "W-6", "W-7"])


def test_resolve_metric_caliber_ambiguity():
    # 采油井的"产量"有两个口径 → 需澄清
    assert len(resolve_metric("产量", "oil")) == 2
    # 明确口径唯一
    assert [p.metric for p in resolve_metric("井口日产量", "oil")] == ["井口日产量"]
    # 井型不匹配
    assert resolve_metric("日产气量", "oil") == []


def test_tag_roundtrip():
    spec = spec_by_suffix("daily_oil_prod")
    tag = tag_for(spec, "W-3")
    assert tag == "W3.daily_oil_prod"
    assert split_tag(tag) == ("W-3", "daily_oil_prod")


def test_scada_decline_and_gap():
    res = query_series("W3.submergence", f"{DATE} 00:00", f"{DATE} 23:59")
    assert res.metric == "沉没度"
    assert res.series[-1].value < res.series[0].value  # 持续下行
    assert res.quality.get("gap")  # 02:00~04:00 缺口


def test_scada_normal_well_no_decline():
    res = query_series("W1.pump_efficiency", f"{DATE} 00:00", f"{DATE} 23:59")
    assert abs(res.series[-1].value - res.series[0].value) < 0.1


def test_knowledge_search_hits():
    hits = search_knowledge("抽油机供液不足怎么处理")
    assert hits
    assert any("供液不足" in h["tags"] or "供液不足" in h["text"] for h in hits)
    assert search_knowledge("完全没有的名词xyz") == []


def test_calendar_known_event():
    evs = events_in_range("W-1", f"{DATE} 00:00", f"{DATE} 23:59")
    assert any(e.event_type == "检修" for e in evs)
    assert find_event("W-1", at(0, "10:00")) is not None
    assert find_event("W-3", at(0, "10:00")) is None
