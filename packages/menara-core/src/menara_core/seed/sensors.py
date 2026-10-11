"""Synthetic smart-city sensors: two water-level sensors per town that follow the local river gauge, a rain gauge and an
air-quality sensor, with a reading every 15 minutes from minute -1440 to 720. Fictional owners, invented readings.

The water sensors share the gauge's warning and danger levels: one sits at the gauge (a small offset below it), one is
upstream and lags the gauge by two hours, so it can warn before the gauge does. Rain is heavy in the flood region
(Kelantan) around T0 and light elsewhere. Own random stream so every older table is unchanged.
"""

from __future__ import annotations

import math
import random
import sqlite3

from menara_core.geo import haversine_km
from menara_core.seed.towers import TowerRow

PERIOD = (-1440, 720)
STEP_MIN = 15
WATER_SENSORS = (("Gauge-side", 0, -0.3), ("Upstream", 120, -1.5))  # (label, lag in minutes behind the gauge, offset in m)
RAIN_WARN, RAIN_DANGER = 20.0, 40.0
AIR_WARN, AIR_DANGER = 55.0, 150.0
FLOOD_STATE = "Kelantan"
NOISE_WATER = 0.03


def _interp(points: list[tuple[int, float]], t: float) -> float:
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:], strict=False):
        if t0 <= t <= t1:
            return v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return points[-1][1]


def build_sensors(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    rng = random.Random(f"{seed}:sensors")
    gauges = conn.execute("SELECT gauge_id, lat, lng, warning_m, danger_m FROM flood_gauge ORDER BY gauge_id").fetchall()
    series = {
        g[0]: [(int(t), float(v)) for t, v in conn.execute("SELECT t_min, level_m FROM flood_reading WHERE gauge_id = ? ORDER BY t_min", (g[0],))]
        for g in gauges
    }
    by_town: dict[str, list[TowerRow]] = {}
    for tower in towers:
        by_town.setdefault(tower.town, []).append(tower)
    sensors: list[tuple[str, str, str, str, float, float, str, str, str, float, float]] = []
    readings: list[tuple[str, int, float]] = []
    times = list(range(PERIOD[0], PERIOD[1] + 1, STEP_MIN))
    for town in sorted(by_town):
        anchor = by_town[town][0]
        gauge = min(gauges, key=lambda g: haversine_km(anchor.lat, anchor.lng, g[1], g[2]))
        state = anchor.state
        owner = f"{town} District Council (synthetic)"

        def add(
            kind: str, label: str, unit: str, warn: float, danger: float, values: list[float],
            *, town: str = town, anchor: TowerRow = anchor, owner: str = owner,
        ) -> None:
            nearest = min(by_town[town], key=lambda t: haversine_km(anchor.lat + 0.004, anchor.lng + 0.004, t.lat, t.lng))
            sensor_id = f"SNS-{len(sensors) + 1:04d}"
            sensors.append((sensor_id, kind, f"{town} {label} (synthetic)", town, round(anchor.lat + 0.004, 5), round(anchor.lng + 0.004, 5), owner, nearest.enodeb_name, unit, warn, danger))
            readings.extend((sensor_id, t, round(v, 2)) for t, v in zip(times, values, strict=True))

        for label, lag, offset in WATER_SENSORS:
            values = [_interp(series[gauge[0]], t - lag) + offset + rng.uniform(-NOISE_WATER, NOISE_WATER) for t in times]
            add("WATER_LEVEL", f"{label} Water Sensor", "m", gauge[3], gauge[4], values)
        rain = []
        for t in times:
            storm = 36.0 * math.exp(-(((t + 300) / 260.0) ** 2)) if state == FLOOD_STATE else 0.0
            rain.append(max(0.0, 1.5 + storm + rng.uniform(-1.0, 1.0) + (4.0 * rng.random() if rng.random() < 0.05 else 0.0)))
        add("RAIN", "Rain Gauge", "mm/h", RAIN_WARN, RAIN_DANGER, rain)
        air = [35.0 + 12.0 * math.sin((t + 420) / 1440.0 * 2 * math.pi) + rng.uniform(-4.0, 4.0) for t in times]
        add("AIR_QUALITY", "Air Quality Sensor", "ug/m3 PM2.5", AIR_WARN, AIR_DANGER, [max(5.0, v) for v in air])
    conn.executemany("INSERT INTO iot_sensor VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", sensors)
    conn.executemany("INSERT INTO iot_reading VALUES (?, ?, ?)", readings)