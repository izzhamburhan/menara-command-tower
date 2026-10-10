from __future__ import annotations

from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from tower_mcp import tools
from tower_mcp.source import TowerSource

KK_BBOX = (5.40, 102.10, 5.70, 102.30)


def test_status_of_flooded_tower_at_t0(source: TowerSource) -> None:
    env = tools.get_status(source, "KKRI-0142")
    assert env.synthetic is True
    assert env.data.status == "DOWN"
    assert env.data.battery_pct == 14
    assert env.data.mains_ok is False
    assert env.data.active_alarm_count == 3
    assert env.data.site_id == "SITE-KKRI-0142"
    assert "KKRI-0142-B1" in env.data.cells
    assert env.evidence[0].source == "tower-mcp"
    assert env.evidence[0].tool == "tower_get_status"
    assert env.evidence[0].ref == "KKRI-0142"


def test_status_lists_overloaded_neighbours(source: TowerSource) -> None:
    env = tools.get_status(source, "KKRI-0142")
    loaded = {n.enodeb_name: n.prb_util for n in env.data.neighbours if (n.prb_util or 0) >= 90}
    assert loaded == {"KKRI-0143": 91.0, "KKRI-0144": 91.0}


def test_status_before_incident_is_up(source: TowerSource, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    env = tools.get_status(source, "KKRI-0142")
    assert env.data.status == "UP"
    assert env.data.active_alarm_count == 0


def test_status_rejects_malformed_and_unknown_ids(source: TowerSource) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_status(source, "kkri142")
    with pytest.raises(NotFoundError):
        tools.get_status(source, "ZZZZ-9999")


def test_bbox_returns_the_kuala_krai_cluster(source: TowerSource) -> None:
    env = tools.list_in_bbox(source, *KK_BBOX)
    names = {t.enodeb_name for t in env.data.towers}
    assert len(names) == 12
    assert all(n.startswith("KKRI-") for n in names)
    assert env.data.truncated is False


def test_bbox_status_filter(source: TowerSource) -> None:
    env = tools.list_in_bbox(source, *KK_BBOX, status="DOWN")
    assert [t.enodeb_name for t in env.data.towers] == ["KKRI-0142"]


def test_bbox_truncates_and_warns(source: TowerSource) -> None:
    env = tools.list_in_bbox(source, 0.0, 95.0, 8.0, 120.0, limit=5)
    assert env.data.returned == 5
    assert env.data.truncated is True
    assert env.warnings


@pytest.mark.parametrize(
    "bbox",
    [(6.0, 100.0, 5.0, 101.0), (0.0, 100.0, 95.0, 101.0), (0.0, 101.0, 1.0, 100.0)],
)
def test_bbox_rejects_bad_bounds(source: TowerSource, bbox: tuple[float, float, float, float]) -> None:
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(source, *bbox)


def test_bbox_rejects_bad_status_and_limit(source: TowerSource) -> None:
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(source, *KK_BBOX, status="BROKEN")
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(source, *KK_BBOX, limit=0)


def test_kpi_window_shows_overload_ramp(source: TowerSource) -> None:
    env = tools.get_kpi(source, "KKRI-0143", window_min=30)
    assert env.data.summary.max_prb_util == 91.0
    assert env.data.summary.samples == len(env.data.points) > 0
    assert env.data.points == sorted(env.data.points, key=lambda p: p.at)


def test_kpi_of_down_tower_is_zero(source: TowerSource) -> None:
    env = tools.get_kpi(source, "KKRI-0142", window_min=5)
    assert env.data.points[-1].throughput_mbps == 0.0


def test_kpi_empty_window_warns(source: TowerSource, set_clock: Callable[[int], None]) -> None:
    set_clock(-5000)
    env = tools.get_kpi(source, "KKRI-0142", window_min=60)
    assert env.data.points == []
    assert env.data.summary.avg_prb_util is None
    assert env.warnings


@pytest.mark.parametrize("window", [0, 4, 1441])
def test_kpi_rejects_bad_window(source: TowerSource, window: int) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_kpi(source, "KKRI-0142", window_min=window)


def test_alarms_for_tower_most_severe_first(source: TowerSource) -> None:
    env = tools.get_alarms(source, enodeb_name="KKRI-0142")
    codes = [a.code for a in env.data.alarms]
    assert set(codes) == {"MAINS_FAIL", "LOW_BATTERY", "SITE_DOWN"}
    assert env.data.alarms[0].severity == "CRITICAL"
    assert all(a.active for a in env.data.alarms)


def test_alarms_only_show_what_has_been_raised(source: TowerSource, set_clock: Callable[[int], None]) -> None:
    set_clock(-100)
    codes = {a.code for a in tools.get_alarms(source, enodeb_name="KKRI-0142").data.alarms}
    assert codes == {"MAINS_FAIL"}


def test_alarms_severity_filter_and_unknown_tower(source: TowerSource) -> None:
    env = tools.get_alarms(source, enodeb_name="KKRI-0143", severity="WARNING")
    assert [a.code for a in env.data.alarms] == ["TRAFFIC_OVERLOAD"]
    with pytest.raises(NotFoundError):
        tools.get_alarms(source, enodeb_name="ZZZZ-9999")
    with pytest.raises(InvalidInputError):
        tools.get_alarms(source, severity="LOUD")


def test_alarm_list_includes_cluster_critical_alarms(source: TowerSource) -> None:
    env = tools.get_alarms(source, severity="CRITICAL")
    assert "KKRI-0142" in {a.enodeb_name for a in env.data.alarms}
