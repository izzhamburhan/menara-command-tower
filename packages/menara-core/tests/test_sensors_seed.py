"""Synthetic smart-city sensors: water level, rain and air quality per town, with readings every 15 minutes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db

KINDS = {"WATER_LEVEL", "RAIN", "AIR_QUALITY"}


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("sensors"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_every_town_with_a_gauge_has_water_rain_and_air_sensors_with_fictional_owners(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM iot_sensor").fetchall()
    assert {r["kind"] for r in rows} == KINDS and len({r["sensor_id"] for r in rows}) == len(rows)
    assert all(r["name"].endswith("(synthetic)") and r["owner"].endswith("(synthetic)") for r in rows)
    towns = {r["town"] for r in rows}
    for town in towns:
        kinds = [r["kind"] for r in rows if r["town"] == town]
        assert kinds.count("WATER_LEVEL") == 2 and "RAIN" in kinds and "AIR_QUALITY" in kinds


def test_thresholds_are_ordered_and_water_ones_match_the_local_gauge(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT * FROM iot_sensor"):
        assert r["warn_value"] < r["danger_value"] and r["unit"]
    row = conn.execute("SELECT * FROM iot_sensor WHERE kind = 'WATER_LEVEL' AND town = 'Kuala Krai' ORDER BY sensor_id LIMIT 1").fetchone()
    gauge = conn.execute("SELECT warning_m, danger_m FROM flood_gauge WHERE gauge_id = 'GAUGE-KKRI-01'").fetchone()
    assert (row["warn_value"], row["danger_value"]) == (gauge["warning_m"], gauge["danger_m"])


def test_readings_come_every_15_minutes_from_minus_1440_to_720(conn: sqlite3.Connection) -> None:
    sensor = conn.execute("SELECT sensor_id FROM iot_sensor ORDER BY sensor_id LIMIT 1").fetchone()["sensor_id"]
    times = [r["t_min"] for r in conn.execute("SELECT t_min FROM iot_reading WHERE sensor_id = ? ORDER BY t_min", (sensor,))]
    assert times[0] == -1440 and times[-1] == 720 and len(times) == 145 and set(b - a for a, b in zip(times, times[1:], strict=False)) == {15}


def test_the_kuala_krai_water_sensors_follow_the_river(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT sensor_id FROM iot_sensor WHERE kind = 'WATER_LEVEL' AND town = 'Kuala Krai' ORDER BY sensor_id").fetchall()
    assert len(rows) == 2

    def at(sensor: str, t: int) -> float:
        return float(conn.execute("SELECT value FROM iot_reading WHERE sensor_id = ? AND t_min = ?", (sensor, t)).fetchone()[0])

    gauge = float(conn.execute("SELECT level_m FROM flood_reading WHERE gauge_id = 'GAUGE-KKRI-01' AND t_min = 0").fetchone()[0])  # 26.4 m
    assert abs(at(rows[0]["sensor_id"], 0) - (gauge - 0.3)) < 0.2  # the sensor at the gauge
    assert at(rows[0]["sensor_id"], 0) > at(rows[0]["sensor_id"], -960) + 4  # and it rose through the night
    assert at(rows[1]["sensor_id"], 0) < at(rows[0]["sensor_id"], 0)  # the upstream one lags behind


def test_rain_is_heavy_in_the_flood_region_and_light_elsewhere(conn: sqlite3.Connection) -> None:
    def peak(town: str) -> float:
        return float(
            conn.execute(
                "SELECT MAX(r.value) FROM iot_reading r JOIN iot_sensor s ON s.sensor_id = r.sensor_id WHERE s.kind = 'RAIN' AND s.town = ?", (town,)
            ).fetchone()[0]
        )

    other = conn.execute("SELECT DISTINCT town FROM iot_sensor WHERE town NOT IN ('Kuala Krai') AND kind = 'RAIN' LIMIT 1").fetchone()["town"]
    assert peak("Kuala Krai") > 30 and peak(other) < 25


def test_same_seed_same_sensors(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        for query in ("SELECT * FROM iot_sensor ORDER BY 1", "SELECT * FROM iot_reading ORDER BY 1, 2"):
            assert a.execute(query).fetchall() == b.execute(query).fetchall()