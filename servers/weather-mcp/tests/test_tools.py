from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from weather_mcp import tools

KUALA_KRAI = (5.531, 102.197)
KUALA_LUMPUR = (3.139, 101.687)


def test_kuala_krai_has_had_extreme_rain_by_t0(conn: sqlite3.Connection) -> None:
    env = tools.get_rainfall(conn, *KUALA_KRAI)
    assert env.synthetic is True
    assert env.data.station.station_id == "WX-KKRI-01"
    assert env.data.station.distance_km < 1
    assert env.data.total_mm == 148.0
    assert env.data.rain_24h_mm == 148.0
    assert env.data.intensity == "VERY_HEAVY"
    assert env.data.last_hour_mm == 25.0 and env.data.peak_mm_per_hour == 25.0
    assert len(env.data.points) == 24
    assert env.evidence[0].tool == "weather_get_rainfall" and env.evidence[0].ref == "WX-KKRI-01"


def test_rain_builds_up_over_time(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    earlier = tools.get_rainfall(conn, *KUALA_KRAI).data
    assert earlier.rain_24h_mm < 148.0
    set_clock(0)
    assert tools.get_rainfall(conn, *KUALA_KRAI).data.rain_24h_mm == 148.0


def test_shorter_window_totals_less_but_keeps_24h_figure(conn: sqlite3.Connection) -> None:
    data = tools.get_rainfall(conn, *KUALA_KRAI, window_min=180).data
    assert data.total_mm == 18.0 + 18.0 + 25.0
    assert data.rain_24h_mm == 148.0


def test_other_regions_are_not_flooded(conn: sqlite3.Connection) -> None:
    data = tools.get_rainfall(conn, *KUALA_LUMPUR).data
    assert data.station.station_id == "WX-KULP-01"
    assert data.intensity in {"NORMAL", "HEAVY"}


def test_lightning_is_severe_at_t0(conn: sqlite3.Connection) -> None:
    data = tools.get_lightning(conn, *KUALA_KRAI).data
    assert data.last_hour_strikes == 150 and data.activity == "SEVERE"
    assert data.total_strikes == 150


def test_lightning_was_quiet_long_before(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-1000)
    assert tools.get_lightning(conn, *KUALA_KRAI).data.activity in {"NONE", "LOW"}


def test_no_station_in_range_is_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="No weather station"):
        tools.get_rainfall(conn, 0.0, 105.0, radius_km=30)


def test_empty_window_warns(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-5000)
    env = tools.get_rainfall(conn, *KUALA_KRAI, window_min=60)
    assert env.data.points == [] and env.data.total_mm == 0.0 and env.warnings


@pytest.mark.parametrize(
    "kwargs",
    [{"lat": 91.0}, {"lng": 181.0}, {"window_min": 59}, {"window_min": 1441}, {"radius_km": 0.5}, {"radius_km": 101.0}],
)
def test_validation(conn: sqlite3.Connection, kwargs: dict[str, float]) -> None:
    args: dict[str, float] = {"lat": KUALA_KRAI[0], "lng": KUALA_KRAI[1], **kwargs}
    with pytest.raises(InvalidInputError):
        tools.get_rainfall(conn, **args)  # type: ignore[arg-type]


def test_label_thresholds() -> None:
    assert [tools.intensity_for(x) for x in (0, 59.9, 60, 119.9, 120, 180)] == [
        "NORMAL",
        "NORMAL",
        "HEAVY",
        "HEAVY",
        "VERY_HEAVY",
        "EXTREME",
    ]
    assert [tools.activity_for(x) for x in (0, 1, 20, 100)] == ["NONE", "LOW", "HIGH", "SEVERE"]
