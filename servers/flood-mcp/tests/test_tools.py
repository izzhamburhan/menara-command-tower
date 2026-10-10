from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from flood_mcp import tools
from menara_core.errors import InvalidInputError, NotFoundError

HUB = (5.531, 102.197)  # KKRI-0142
KUALA_LUMPUR = (3.139, 101.687)
KELANTAN_BBOX = (4.5, 101.5, 6.5, 102.6)


def test_river_is_above_danger_and_rising_at_t0(conn: sqlite3.Connection) -> None:
    env = tools.get_gauge(conn, "GAUGE-KKRI-01")
    assert env.synthetic is True
    assert env.data.level_m == 26.4
    assert env.data.status == "DANGER" and env.data.trend == "RISING"
    assert env.data.above_danger_by_m == 1.4
    assert env.evidence[0].tool == "flood_get_gauge" and env.evidence[0].ref == "GAUGE-KKRI-01"


def test_river_rises_through_warning_to_danger(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    assert tools.get_gauge(conn, "GAUGE-KKRI-01").data.status == "WARNING"
    set_clock(-1000)
    assert tools.get_gauge(conn, "GAUGE-KKRI-01").data.status == "NORMAL"


def test_river_recedes_after_the_peak(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(420)
    data = tools.get_gauge(conn, "GAUGE-KKRI-01").data
    assert data.trend == "FALLING"


def test_other_rivers_are_normal(conn: sqlite3.Connection) -> None:
    assert tools.get_gauge(conn, "GAUGE-KULP-01").data.status == "NORMAL"


def test_list_gauges_in_a_box_and_by_status(conn: sqlite3.Connection) -> None:
    everything = tools.list_gauges(conn, *KELANTAN_BBOX).data
    assert "GAUGE-KKRI-01" in {g.gauge_id for g in everything.gauges}
    danger = tools.list_gauges(conn, *KELANTAN_BBOX, status="DANGER").data
    assert [g.gauge_id for g in danger.gauges] == ["GAUGE-KKRI-01"]
    assert tools.list_gauges(conn, 0.0, 95.0, 8.0, 120.0, limit=3).data.truncated is True


def test_hub_tower_is_flooded_at_t0(conn: sqlite3.Connection) -> None:
    env = tools.check_point(conn, *HUB)
    assert env.data.inside_flood is True
    assert env.data.extent_id == "EXT-KKRI-03" and env.data.extent_radius_km == 4.5
    assert env.data.depth_m is not None and 0.9 < env.data.depth_m < 1.2
    assert env.data.distance_to_edge_km == 0.0


def test_flood_grows_over_time(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-100)
    early = tools.check_point(conn, *HUB).data
    assert early.extent_id == "EXT-KKRI-01" and early.inside_flood is True
    assert early.depth_m is not None and early.depth_m < 0.3
    set_clock(200)
    late = tools.check_point(conn, *HUB).data
    assert late.extent_id == "EXT-KKRI-04" and late.extent_radius_km == 6.0


def test_a_distant_point_is_dry(conn: sqlite3.Connection) -> None:
    data = tools.check_point(conn, *KUALA_LUMPUR).data
    assert data.inside_flood is False and data.depth_m == 0.0
    assert data.distance_to_edge_km is not None and data.distance_to_edge_km > 100


def test_no_extent_before_the_flood_starts(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-500)
    env = tools.check_point(conn, *HUB)
    assert env.data.inside_flood is False and env.data.extent_id is None and env.warnings


def test_validation_and_unknown_ids(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_gauge(conn, "KKRI-01")
    with pytest.raises(NotFoundError):
        tools.get_gauge(conn, "GAUGE-ZZZZ-99")
    with pytest.raises(InvalidInputError):
        tools.list_gauges(conn, 6.0, 100.0, 5.0, 101.0)
    with pytest.raises(InvalidInputError):
        tools.list_gauges(conn, *KELANTAN_BBOX, status="WET")
    with pytest.raises(InvalidInputError):
        tools.list_gauges(conn, *KELANTAN_BBOX, limit=0)
    with pytest.raises(InvalidInputError):
        tools.check_point(conn, 95.0, 100.0)


def test_status_thresholds() -> None:
    assert [tools.status_for(x, 23.0, 25.0) for x in (22.9, 23.0, 24.9, 25.0)] == [
        "NORMAL",
        "WARNING",
        "WARNING",
        "DANGER",
    ]
