"""Synthetic subscriber movement: which cell each subscriber was on, over the seeded period.

Generated last, with its own random stream, so every older table in the seed is unchanged. A subscriber is on
Generated last, with its own random streams, so every older table in the seed is unchanged. A subscriber is on
their `subscriber.serving_cell` at scenario minute 0. About half of the subscribers who have a suitable
work tower commute (home, a tower on the way, work, and back the day before); the rest, and everyone on the
flood-cluster towers, stay where they are.

The seeded period starts four weeks before T0 (minute -40320, a Saturday). A commuter's last two days (from
minute -1440) are the original commute. The 26 days before that follow a weekly routine: Monday to Friday the same
commute, and at the weekend either home or a trip to a synthetic mall (about 40% of commuters with a mall 3 to
25 km away are mall regulars). All of it is synthetic.
"""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from datetime import datetime, timedelta

from menara_core.geo import bbox_around, haversine_km
from menara_core.privacy import coarsen_location
from menara_core.scenario import Scenario

PERIOD_START = -1440
PERIOD_START = -1440  # yesterday 07:00: where the original two-day commute begins
HISTORY_DAYS = 28
HISTORY_START = -HISTORY_DAYS * 1440  # a Saturday, 07:00
MOVER_SHARE = 0.5  # of subscribers that have a candidate work tower
WORK_MIN_KM, WORK_MAX_KM = 5.0, 25.0
DEPART_MORNING = 60  # 08:00, minutes after T0 (07:00)
DEPART_EVENING = 630  # 17:30
EN_ROUTE_MIN = 30
JITTER_MIN = 45
MALL_MIN_KM, MALL_MAX_KM = 3.0, 25.0
MALL_REGULAR_SHARE = 0.4
REGULAR_WEEKEND_CHANCE = 0.8
OCCASIONAL_WEEKEND_CHANCE = 0.1
MALL_START_MIN = (180, 420)  # 10:00 to 14:00, minutes after 07:00
MALL_STAY_MIN = (120, 240)

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


def _mall_options(towers: list[Tower], home: Tower, malls: list[str]) -> list[str]:
    by_name = {t[0]: t for t in towers}
    return [
        m
        for m in malls
        if m != home[0] and MALL_MIN_KM <= haversine_km(home[1], home[2], by_name[m][1], by_name[m][2]) <= MALL_MAX_KM
    ]


def _history(
    rng: random.Random,
    t0: datetime,
    home: str,
    work: str,
    mid: str | None,
    malls: list[str],
    regular: bool,
    pick_cell: Callable[[str], str],
) -> list[tuple[int, str, str]]:
    """Rows (start_min, tower, cell) from HISTORY_START up to the evening return home of the day before yesterday.

    The last row is that return: it takes the place of the original first row at minute -1440 (also home).
    """
    rows: list[tuple[int, str, str]] = [(HISTORY_START, home, pick_cell(home))]

    def move(start: int, tower: str) -> None:
        if rows[-1][1] != tower:
            rows.append((start, tower, pick_cell(tower)))

    for day in range(-HISTORY_DAYS, -1):  # day -28 (a Saturday) up to day -2
        day_start = day * 1440
        if (t0 + timedelta(days=day)).weekday() < 5:
            morning = day_start + DEPART_MORNING + rng.randint(-JITTER_MIN, JITTER_MIN)
            evening = day_start + DEPART_EVENING + rng.randint(-JITTER_MIN, JITTER_MIN)
            for depart, destination in ((morning, work), (evening, home)):
                if mid is not None:
                    move(depart, mid)
                move(depart + (EN_ROUTE_MIN if mid is not None else 0), destination)
        elif malls and (t0 + timedelta(days=day)).weekday() == 5:  # Saturday: decide for the whole weekend
            chance = REGULAR_WEEKEND_CHANCE if regular else OCCASIONAL_WEEKEND_CHANCE
            if rng.random() < chance:
                mall = malls[0] if regular else rng.choice(malls)
                start = day_start + 1440 * rng.randint(0, 1) + rng.randint(*MALL_START_MIN)
                move(start, mall)
                move(start + rng.randint(*MALL_STAY_MIN), home)
    return rows


def build_movement(conn: sqlite3.Connection, seed: int, scenario: Scenario) -> None:
    rng = random.Random(f"{seed}:movement")
    history_rng = random.Random(f"{seed}:history")  # separate, so the last two days stay exactly as they were
    t0 = datetime.fromisoformat(scenario.start)
    malls = sorted({name for (name,) in conn.execute("SELECT serving_enodeb FROM critical_site WHERE kind = 'MALL'")})
    towers = _towers(conn)
    by_name = {t[0]: t for t in towers}
    cluster = {t.enodeb for t in scenario.cluster.towers}
    cells: dict[str, list[str]] = {}
    for cell_id, name in conn.execute("SELECT cell_id, enodeb_name FROM cell ORDER BY cell_id"):
        cells.setdefault(name, []).append(cell_id)
    work_cache: dict[str, list[str]] = {}
    mid_cache: dict[tuple[str, str], str | None] = {}
    mall_cache: dict[str, list[str]] = {}

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
            rows.append(row(sub, HISTORY_START, home, home_cell))
            continue
        work = rng.choice(options)
        if (home, work) not in mid_cache:
            mid_cache[(home, work)] = _en_route(towers, by_name[home], by_name[work])
        if home not in mall_cache:
            mall_cache[home] = _mall_options(towers, by_name[home], malls)
        near = mall_cache[home]
        regular = bool(near) and history_rng.random() < MALL_REGULAR_SHARE
        trips = [history_rng.choice(near)] if regular else near

        def history_cell(tower: str, home: str = home, home_cell: str = home_cell) -> str:
            return home_cell if tower == home else history_rng.choice(cells[tower])

        for start, tower, cell in _history(history_rng, t0, home, work, mid_cache[(home, work)], trips, regular, history_cell):
            rows.append(row(sub, start, tower, cell))
        for start, tower in _commute(rng, home, work, mid_cache[(home, work)])[1:]:  # the original first row (home, -1440) is the history's last
            cell = home_cell if tower == home else rng.choice(cells[tower])
            rows.append(row(sub, start, tower, cell))
    conn.executemany("INSERT INTO subscriber_cell_visit VALUES (?, ?, ?, ?, ?, ?)", rows)