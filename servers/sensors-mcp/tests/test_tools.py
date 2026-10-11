"""sensors-mcp tools: smart-city sensors and early-warning alerts. Fictional sensors; the water ones follow the river gauge."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from sensors_mcp import tools

KUALA_KRAI = (5.531, 102.197)


def sensor_ids(conn: sqlite3.Connection, town: str, kind: str) -> list[str]:
    return [r["sensor_id"] for r in conn.execute("SELECT sensor_id FROM iot_sensor WHERE town = ? AND kind = ? ORDER BY sensor_id", (town, kind))]


def test_sensors_in_a_circle_have_the_latest_value_unit_and_status(conn: sqlite3.Connection) -> None:
    env = tools.list_in_area(conn, *KUALA_KRAI, 20.0)
    data = env.data
    assert env.synthetic is True and env.evidence[0].tool == "sensors_list_in_area" and data.returned == len(data.sensors) >= 4
    kinds = {s.kind for s in data.sensors}
    assert {"WATER_LEVEL", "RAIN", "AIR_QUALITY"} <= kinds
    assert all(s.unit and s.status in {"OK", "WARNING", "DANGER"} and s.distance_km <= 20.0 for s in data.sensors)
    water_only = tools.list_in_area(conn, *KUALA_KRAI, 20.0, kind="WATER_LEVEL").data
    assert water_only.sensors and {s.kind for s in water_only.sensors} == {"WATER_LEVEL"}


def test_readings_stop_at_the_clock_and_the_window_is_validated(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    sensor = sensor_ids(conn, "Kuala Krai", "WATER_LEVEL")[0]
    set_clock(0)
    data = tools.get_readings(conn, sensor, 360).data
    times = [p.t_min for p in data.points]
    assert times == sorted(times) and times[-1] == 0 and times[0] >= -360 and len(times) >= 24
    assert data.latest == data.points[-1].value and data.min_value <= data.max_value
    set_clock(-300)
    assert tools.get_readings(conn, sensor, 60).data.points[-1].t_min == -300
    for window in (4, 1441):
        with pytest.raises(InvalidInputError):
            tools.get_readings(conn, sensor, window)
    with pytest.raises(NotFoundError):
        tools.get_readings(conn, "SNS-9999", 60)


def test_alerts_at_t0_include_the_kuala_krai_water_sensors_and_exclude_quiet_places(conn: sqlite3.Connection) -> None:
    alerts = tools.get_alerts(conn, *KUALA_KRAI, 20.0).data.alerts
    water = {a.sensor_id for a in alerts if a.kind == "WATER_LEVEL"}
    assert set(sensor_ids(conn, "Kuala Krai", "WATER_LEVEL")) <= water
    quiet = tools.get_alerts(conn, 3.139, 101.687, 20.0).data  # Kuala Lumpur
    assert quiet.alerts == [] and quiet.returned == 0


def test_a_sensor_over_danger_is_marked_danger_with_zero_minutes_and_a_rising_one_has_a_projection(conn: sqlite3.Connection) -> None:
    alerts = {a.sensor_id: a for a in tools.get_alerts(conn, *KUALA_KRAI, 20.0).data.alerts}
    gauge_side, upstream = sensor_ids(conn, "Kuala Krai", "WATER_LEVEL")
    assert alerts[gauge_side].status == "DANGER" and alerts[gauge_side].projected_min_to_danger == 0
    assert alerts[upstream].status in {"WARNING", "DANGER"}
    if alerts[upstream].status == "WARNING":
        assert alerts[upstream].trend_per_hour > 0 and (alerts[upstream].projected_min_to_danger or 0) > 0


def test_a_falling_sensor_has_no_projected_time_to_danger(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(470)  # the river is past its peak and falling
    alerts = tools.get_alerts(conn, *KUALA_KRAI, 20.0, kind="WATER_LEVEL").data.alerts
    falling = [a for a in alerts if a.status == "WARNING"]
    assert all(a.trend_per_hour <= 0 and a.projected_min_to_danger is None for a in falling)


def test_alerts_are_sorted_most_urgent_first(conn: sqlite3.Connection) -> None:
    alerts = tools.get_alerts(conn, *KUALA_KRAI, 20.0).data.alerts
    ranks = [0 if a.status == "DANGER" else 1 for a in alerts]
    assert ranks == sorted(ranks)
    dangers = [a.value / a.danger_value for a in alerts if a.status == "DANGER"]
    assert dangers == sorted(dangers, reverse=True)


@pytest.mark.parametrize("kwargs", [{"radius_km": 0.0}, {"radius_km": 101.0}, {"kind": "SMOKE"}, {"lat": 91.0}, {"lng": 181.0}])
def test_bad_inputs_are_invalid(conn: sqlite3.Connection, kwargs: dict[str, object]) -> None:
    args: dict[str, object] = {"lat": 5.5, "lng": 102.1, "radius_km": 10.0}
    args.update(kwargs)
    with pytest.raises(InvalidInputError):
        tools.list_in_area(conn, **args)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        tools.get_alerts(conn, **args)  # type: ignore[arg-type]
