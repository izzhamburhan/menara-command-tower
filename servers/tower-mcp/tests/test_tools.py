from __future__ import annotations

from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from tower_mcp import tools
from tower_mcp.models import TowerPin
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


# ---------- tower_list_in_radius ----------

KK_CENTRE = (5.531, 102.197)  # KKRI-0142


class BoxSource:
    """A source that only knows how to list towers in a box, like a real API behind the HTTP source."""

    synthetic = True

    def __init__(self, pins: list[TowerPin]) -> None:
        self.pins = pins

    def as_of(self) -> str:
        return "2026-11-14T07:00:00+08:00"

    def list_towers(
        self, min_lat: float, min_lng: float, max_lat: float, max_lng: float, status: str | None, limit: int
    ) -> list[TowerPin]:
        inside = [p for p in self.pins if min_lat <= p.lat <= max_lat and min_lng <= p.lng <= max_lng]
        return sorted(inside, key=lambda p: p.enodeb_name)[:limit]


def pin(name: str, lat: float, lng: float) -> TowerPin:
    return TowerPin(enodeb_name=name, site_id=f"SITE-{name}", town="T", state="S", lat=lat, lng=lng, status="UP")


def test_radius_returns_towers_nearest_first_with_distance(source: TowerSource) -> None:
    env = tools.list_in_radius(source, *KK_CENTRE, radius_km=5)
    names = [t.enodeb_name for t in env.data.towers]
    assert names[0] == "KKRI-0142" and env.data.towers[0].distance_km == 0.0
    assert "KKRI-0143" in names and next(t for t in env.data.towers if t.enodeb_name == "KKRI-0143").distance_km == pytest.approx(3.069, abs=0.01)
    distances = [t.distance_km for t in env.data.towers]
    assert distances == sorted(distances) and max(distances) <= 5
    assert env.data.center.lat == KK_CENTRE[0] and env.data.radius_km == 5
    assert env.evidence[0].tool == "tower_list_in_radius" and env.synthetic is True


def test_a_tower_in_the_box_corner_but_outside_the_circle_is_excluded() -> None:
    lat, lng = 5.5, 102.2
    corner = pin("AAAA-0001", lat + 0.085, lng + 0.085)  # inside the 10 km box, about 13 km away
    near = pin("AAAA-0002", lat + 0.03, lng)  # about 3.3 km away
    env = tools.list_in_radius(BoxSource([corner, near]), lat, lng, radius_km=10)  # type: ignore[arg-type]
    assert [t.enodeb_name for t in env.data.towers] == ["AAAA-0002"]


def test_radius_status_filter_and_limit_truncation(source: TowerSource) -> None:
    down = tools.list_in_radius(source, *KK_CENTRE, radius_km=20, status="DOWN").data
    assert [t.enodeb_name for t in down.towers] == ["KKRI-0142"]
    few = tools.list_in_radius(source, *KK_CENTRE, radius_km=50, limit=2)
    assert few.data.returned == 2 and few.data.truncated is True and few.warnings
    assert few.data.towers[0].enodeb_name == "KKRI-0142"  # the nearest are kept


def test_radius_warns_when_the_box_prefetch_overflows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MAX_LIMIT", 3)
    crowd = BoxSource([pin(f"AAAA-{i:04d}", 5.5 + i * 0.001, 102.2) for i in range(10)])
    env = tools.list_in_radius(crowd, 5.5, 102.2, radius_km=10, limit=3)  # type: ignore[arg-type]
    assert any("may be missing" in w for w in env.warnings)


@pytest.mark.parametrize(
    "args",
    [
        {"lat": 91.0, "lng": 102.0, "radius_km": 5},
        {"lat": 5.0, "lng": 181.0, "radius_km": 5},
        {"lat": 5.0, "lng": 102.0, "radius_km": 0.05},
        {"lat": 5.0, "lng": 102.0, "radius_km": 201},
        {"lat": 5.0, "lng": 102.0, "radius_km": 5, "status": "BROKEN"},
        {"lat": 5.0, "lng": 102.0, "radius_km": 5, "limit": 0},
        {"lat": 5.0, "lng": 102.0, "radius_km": 5, "limit": 2001},
    ],
)
def test_radius_validation(source: TowerSource, args: dict[str, float | str | int]) -> None:
    with pytest.raises(InvalidInputError):
        tools.list_in_radius(source, **args)  # type: ignore[arg-type]

