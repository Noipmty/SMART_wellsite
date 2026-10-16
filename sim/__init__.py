"""仿真数据源包：统一对外出口（mock SCADA / 环境 / 视频 / 知识库 / 井号表 / 点表 / 日历）。"""

from sim.calendar import CalendarEvent, events_in_range, find_event
from sim.env_video import (
    ENV_THRESHOLDS,
    ENV_UNITS,
    describe_frame,
    level_for,
    query_env,
    query_video,
    video_events_as_perception,
)
from sim.knowledge import search_knowledge
from sim.points import POINTS, PointSpec, resolve_metric, spec_by_suffix, split_tag, tag_for
from sim.registry import WELLS, Well, candidate_wells, list_well_ids, normalize_well
from sim.scada import query_series

__all__ = [
    "WELLS",
    "Well",
    "normalize_well",
    "candidate_wells",
    "list_well_ids",
    "POINTS",
    "PointSpec",
    "resolve_metric",
    "spec_by_suffix",
    "tag_for",
    "split_tag",
    "CalendarEvent",
    "events_in_range",
    "find_event",
    "query_series",
    "query_env",
    "query_video",
    "level_for",
    "describe_frame",
    "video_events_as_perception",
    "ENV_THRESHOLDS",
    "ENV_UNITS",
    "search_knowledge",
]
