"""Synthetic context data: weather stations and observations, grid feeders, river gauges and flood extents."""

from __future__ import annotations

import random
import sqlite3

from menara_core.scenario import Scenario
from menara_core.seed.towers import TOWNS, TowerRow

OBS_START, OBS_END, OBS_STEP = -1440, 480, 60
FEEDER_SIZE = 4
HOURLY = range(OBS_START, OBS_END + 1, OBS_STEP)


def _station_id(code: str) -> str:
    return f"WX-{code}-01"


def _make_weather(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario) -> None:
    for code, town, state, lat, lng, _w, _r in TOWNS:
        station = _station_id(code)
        conn.execute(
            "INSERT INTO weather_station VALUES (?, ?, ?, ?, ?, ?)",
            (station, f"{town} (synthetic station)", town, state, lat, lng),
        )
        wet = rng.uniform(0.05, 0.5)
        for t_min in HOURLY:
            rain = round(rng.uniform(0.5, 4 * wet + 1), 1) if rng.random() < wet else 0.0
            lightning = int(rng.uniform(0, 40)) if rain > 3 else 0
            conn.execute(
                "INSERT INTO weather_obs VALUES (?, ?, ?, ?, ?)",
                (station, t_min, rain, lightning, round(rng.uniform(5, 25), 1)),
            )
    spec = scenario.weather
    conn.execute(
        "INSERT INTO weather_station VALUES (?, ?, ?, ?, ?, ?)",
        (spec.station.id, spec.station.name, scenario.cluster.town, scenario.cluster.state, spec.station.lat, spec.station.lng),
    )
    steps = sorted(spec.rain_profile, key=lambda s: s.from_min)
    for t_min in HOURLY:
        step = max((s for s in steps if s.from_min <= t_min), key=lambda s: s.from_min)
        wind = round(rng.uniform(25, 45), 1) if step.mm >= 10 else round(rng.uniform(5, 20), 1)
        conn.execute("INSERT INTO weather_obs VALUES (?, ?, ?, ?, ?)", (spec.station.id, t_min, step.mm, step.lightning, wind))


def _make_grid(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow]) -> None:
    cluster_names = {t.enodeb for t in scenario.cluster.towers}
    by_town: dict[str, list[TowerRow]] = {}
    for tower in towers:
        if tower.enodeb_name not in cluster_names:
            by_town.setdefault(tower.town, []).append(tower)
    codes = {town: code for code, town, *_ in TOWNS}
    for town, rows in by_town.items():
        rows.sort(key=lambda t: (t.lat, t.lng, t.enodeb_name))
        for index in range(0, len(rows), FEEDER_SIZE):
            chunk = rows[index : index + FEEDER_SIZE]
            feeder = f"FDR-{codes[town]}-{index // FEEDER_SIZE + 1:02d}"
            conn.execute(
                "INSERT INTO grid_feeder VALUES (?, ?, ?, ?)",
                (feeder, f"{town} Feeder {index // FEEDER_SIZE + 1:02d} (synthetic)", chunk[0].state, rng.randint(1500, 9000)),
            )
            conn.execute("INSERT INTO grid_feeder_state VALUES (?, -1440, 'ENERGISED', 'Normal supply', NULL)", (feeder,))
            conn.executemany("INSERT INTO grid_feeder_tower VALUES (?, ?)", [(t.enodeb_name, feeder) for t in chunk])
    for spec in scenario.grid.feeders:
        conn.execute(
            "INSERT INTO grid_feeder VALUES (?, ?, ?, ?)", (spec.id, spec.name, scenario.cluster.state, spec.customers)
        )
        conn.execute("INSERT INTO grid_feeder_state VALUES (?, -1440, 'ENERGISED', 'Normal supply', NULL)", (spec.id,))
        conn.executemany("INSERT INTO grid_feeder_tower VALUES (?, ?)", [(name, spec.id) for name in spec.towers])
    for event in scenario.grid.events:
        conn.execute(
            "INSERT INTO grid_feeder_state VALUES (?, ?, ?, ?, ?)",
            (event.feeder, event.t_min, event.status, event.note, event.restoration_eta_min),
        )


def _interpolate(points: list[tuple[int, float]], t_min: int) -> float:
    ordered = sorted(points)
    if t_min <= ordered[0][0]:
        return ordered[0][1]
    for (t0, v0), (t1, v1) in zip(ordered, ordered[1:], strict=False):
        if t0 <= t_min <= t1:
            return v0 + (v1 - v0) * (t_min - t0) / (t1 - t0)
    return ordered[-1][1]


def _make_flood(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario) -> None:
    for code, town, state, lat, lng, _w, _r in TOWNS:
        gauge = f"GAUGE-{code}-01"
        warning = round(rng.uniform(8, 20), 1)
        conn.execute(
            "INSERT INTO flood_gauge VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (gauge, f"{town} River (synthetic)", f"{town} (synthetic gauge)", state, lat, lng, warning, warning + 2.0),
        )
        base = warning * rng.uniform(0.4, 0.75)
        for t_min in HOURLY:
            conn.execute("INSERT INTO flood_reading VALUES (?, ?, ?)", (gauge, t_min, round(base + rng.uniform(-0.3, 0.3), 2)))
    spec = scenario.flood.gauge
    conn.execute(
        "INSERT INTO flood_gauge VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (spec.id, spec.river, spec.station, scenario.cluster.state, spec.lat, spec.lng, spec.warning_m, spec.danger_m),
    )
    points = [(p.t_min, p.m) for p in scenario.flood.levels]
    for t_min in HOURLY:
        conn.execute("INSERT INTO flood_reading VALUES (?, ?, ?)", (spec.id, t_min, round(_interpolate(points, t_min), 2)))
    for extent in scenario.flood.extents:
        conn.execute(
            "INSERT INTO flood_extent VALUES (?, ?, ?, ?, ?, ?, ?)",
            (extent.id, extent.name, extent.from_min, extent.lat, extent.lng, extent.radius_km, extent.max_depth_m),
        )


def build_context(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow]) -> None:
    _make_weather(conn, rng, scenario)
    _make_grid(conn, rng, scenario, towers)
    _make_flood(conn, rng, scenario)