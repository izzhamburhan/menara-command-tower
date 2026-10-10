"""Synthetic subscriber movement: which cell each subscriber was on, over the seeded period.

Generated last, with its own random stream, so every older table in the seed is unchanged. A subscriber is on
their `subscriber.serving_cell` at scenario minute 0. About half of the subscribers who have a suitable
work tower commute (home, a tower on the way, work, and back the day before); the rest, and everyone on the
flood-cluster towers, stay where they are.
"""

from __future__ import annotations

import random
import sqlite3

from menara_core.geo import bbox_around, haversine_km
from menara_core.privacy import coarsen_location
from menara_core.scenario import Scenario

PERIOD_START = -1440
MOVER_SHARE = 0.5  # of subscribers that have a candidate work tower
WORK_MIN_KM, WORK_MAX_KM = 5.0, 25.0
DEPART_MORNING = 60  # 08:00, minutes after T0 (07:00)
DEPART_EVENING = 630  # 17:30
EN_ROUTE_MIN = 30
JITTER_MIN = 45

Visit = tuple[int, str]  # (start_min, tower)


Tower = tuple[str, float, float]  # (enodeb_name, lat, lng)


def _towers(conn: sqlite3.Connection) -> list[Tower]:
    return [(n, lat, lng) for n, lat, lng in conn.execute("SELECT enodeb_name, lat, lng FROM tower ORDER BY enodeb_name")]


def _inside_box(tower: Tower, box: tuple[float, float, float, float]) -> bool:
    return box[0] <= tower[1] <= box[2] and box[1] <= tower[2] <= box[3]


def _work_options(towers: list[Tower], home: Tower, excluded: set[str]) -> list[str]:
    """Towers 5 to 25 km from home that are not in the flood cluster."""
    box = bbox_around(home[1], home[2], WORK_MAX_KM)
    return [
        t[0]
        for t in towers
        if t[0] not in excluded
        and _inside_box(t, box)
        and WORK_MIN_KM <= haversine_km(home[1], home[2], t[1], t[2]) <= WORK_MAX_KM
    ]


def _en_route(towers: list[Tower], home: Tower, work: Tower) -> str | None:
    """The tower nearest the midpoint of home and work, if one lies between them."""
    mid = ((home[1] + work[1]) / 2, (home[2] + work[2]) / 2)
    half = haversine_km(home[1], home[2], work[1], work[2]) / 2
    box = bbox_around(*mid, half)
    options = [t for t in towers if t[0] not in (home[0], work[0]) and _inside_box(t, box)]
    if not options:
        return None
    return min(options, key=lambda t: (haversine_km(*mid, t[1], t[2]), t[0]))[0]


def _commute(rng: random.Random, home: str, work: str, mid: str | None) -> list[Visit]:
    """Yesterday: home, work, home. Today, up to the end of the period: home, then on to work.

    Minutes are after T0 (07:00), so yesterday starts at -1440 and today's departure is about 08:00 (minute 60).
    A subscriber is still at home at minute 0, the departure never being earlier than minute 15.
    """
    morning = DEPART_MORNING + rng.randint(-JITTER_MIN, JITTER_MIN)
    evening = DEPART_EVENING + rng.randint(-JITTER_MIN, JITTER_MIN)
    visits: list[Visit] = [(PERIOD_START, home)]

    def leg(depart: int, destination: str) -> None:
        if mid is not None:
            visits.append((depart, mid))
        visits.append((depart + (EN_ROUTE_MIN if mid is not None else 0), destination))

    leg(PERIOD_START + morning, work)
    leg(PERIOD_START + evening, home)
    leg(morning, work)
    return visits


def build_movement(conn: sqlite3.Connection, seed: int, scenario: Scenario) -> None:
    rng = random.Random(f"{seed}:movement")
    towers = _towers(conn)
    by_name = {t[0]: t for t in towers}
    cluster = {t.enodeb for t in scenario.cluster.towers}
    cells: dict[str, list[str]] = {}
    for cell_id, name in conn.execute("SELECT cell_id, enodeb_name FROM cell ORDER BY cell_id"):
        cells.setdefault(name, []).append(cell_id)
    work_cache: dict[str, list[str]] = {}
    mid_cache: dict[tuple[str, str], str | None] = {}

    def row(sub: str, start: int, tower: str, cell: str) -> tuple[object, ...]:
        lat, lng = coarsen_location(by_name[tower][1], by_name[tower][2])
        return (sub, start, cell, tower, lat, lng)

    rows: list[tuple[object, ...]] = []
    subscribers = conn.execute("SELECT msisdn_hash, serving_cell, enodeb_name FROM subscriber ORDER BY msisdn_hash").fetchall()
    for sub, home_cell, home in subscribers:
        if home not in work_cache:
            work_cache[home] = [] if home in cluster else _work_options(towers, by_name[home], cluster)
        options = work_cache[home]
        if not options or rng.random() >= MOVER_SHARE:
            rows.append(row(sub, PERIOD_START, home, home_cell))
            continue
        work = rng.choice(options)
        if (home, work) not in mid_cache:
            mid_cache[(home, work)] = _en_route(towers, by_name[home], by_name[work])
        for start, tower in _commute(rng, home, work, mid_cache[(home, work)]):
            cell = home_cell if tower == home else rng.choice(cells[tower])
            rows.append(row(sub, start, tower, cell))
    conn.executemany("INSERT INTO subscriber_cell_visit VALUES (?, ?, ?, ?, ?, ?)", rows)
