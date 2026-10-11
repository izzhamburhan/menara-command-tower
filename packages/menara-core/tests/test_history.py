"""Four weeks of synthetic movement before the last two days: weekday commutes and weekend mall routines."""

from __future__ import annotations

import hashlib
import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from menara_core import settings
from menara_core.geo import haversine_km
from menara_core.scenario import load_scenario
from menara_core.seed.build import DEFAULT_TOWER_COUNT, build
from menara_core.testing import build_test_db

HISTORY_START = -40320
T0 = datetime(2026, 11, 14, 7, 0)  # a Saturday, 07:00

# Rows after minute -1440, recorded from `main` before the history existed (count, short hash).
LAST_TWO_DAYS = (579, "0ac3d3bc2cf9")


def weekday(minute: int) -> int:
    return (T0 + timedelta(minutes=minute)).weekday()


def is_weekend(minute: int) -> bool:
    return weekday(minute) >= 5


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("history"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def _visits(conn: sqlite3.Connection) -> dict[str, list[tuple[int, str]]]:
    by_sub: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for r in conn.execute("SELECT msisdn_hash, start_min, enodeb_name FROM subscriber_cell_visit ORDER BY msisdn_hash, start_min"):
        by_sub[r["msisdn_hash"]].append((r["start_min"], r["enodeb_name"]))
    return by_sub


def _homes(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["msisdn_hash"]: r["enodeb_name"] for r in conn.execute("SELECT msisdn_hash, enodeb_name FROM subscriber")}


def _mall_towers(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT serving_enodeb FROM critical_site WHERE kind = 'MALL'")}


def _coords(conn: sqlite3.Connection) -> dict[str, tuple[float, float]]:
    return {r["enodeb_name"]: (r["lat"], r["lng"]) for r in conn.execute("SELECT enodeb_name, lat, lng FROM tower")}


def _mall_in_range(conn: sqlite3.Connection, home: str) -> bool:
    coords = _coords(conn)
    return any(3.0 <= haversine_km(*coords[home], *coords[m]) <= 25.0 for m in _mall_towers(conn))


def test_the_last_two_days_of_every_mover_are_unchanged(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM subscriber_cell_visit WHERE start_min > -1440 ORDER BY 1,2").fetchall()
    assert (len(rows), hashlib.sha256(repr([tuple(r) for r in rows]).encode()).hexdigest()[:12]) == LAST_TWO_DAYS


def test_every_subscriber_starts_four_weeks_back(conn: sqlite3.Connection) -> None:
    firsts = conn.execute("SELECT MIN(start_min) AS first FROM subscriber_cell_visit GROUP BY msisdn_hash").fetchall()
    assert {r["first"] for r in firsts} == {HISTORY_START}
    assert weekday(HISTORY_START) == 5  # Saturday 2026-10-17


def test_no_two_consecutive_visits_share_a_tower(conn: sqlite3.Connection) -> None:
    clashes = [
        sub
        for sub, rows in _visits(conn).items()
        if any(a[1] == b[1] for a, b in zip(rows, rows[1:], strict=False))
    ]
    assert clashes == []


def test_weekend_visits_only_go_home_or_to_a_mall_serving_tower(conn: sqlite3.Connection) -> None:
    malls, homes = _mall_towers(conn), _homes(conn)
    stray = [
        (sub, minute, tower)
        for sub, rows in _visits(conn).items()
        for minute, tower in rows
        if minute < -1440 and is_weekend(minute) and tower != homes[sub] and tower not in malls
    ]
    assert stray == []


def test_weekday_history_has_commutes_to_work(conn: sqlite3.Connection) -> None:
    homes = _homes(conn)
    commuters = [
        sub
        for sub, rows in _visits(conn).items()
        if sum(1 for minute, tower in rows if minute < -1440 and not is_weekend(minute) and tower != homes[sub]) >= 10
    ]
    assert len(commuters) > 50


def _weekend_mall_days(conn: sqlite3.Connection) -> dict[str, set[int]]:
    malls, homes = _mall_towers(conn), _homes(conn)
    days: dict[str, set[int]] = defaultdict(set)
    for sub, rows in _visits(conn).items():
        for minute, tower in rows:
            if minute < -1440 and is_weekend(minute) and tower in malls and tower != homes[sub]:
                days[sub].add((minute - HISTORY_START) // 1440)
    return days


def test_a_mall_regular_visits_most_weekends(conn: sqlite3.Connection) -> None:
    weekends = {sub: {d // 7 for d in days} for sub, days in _weekend_mall_days(conn).items()}
    assert any(len(w) >= 3 for w in weekends.values())


def test_a_weekend_mall_visit_lasts_two_to_four_hours(conn: sqlite3.Connection) -> None:
    malls, homes = _mall_towers(conn), _homes(conn)
    lengths = []
    for sub, rows in _visits(conn).items():
        for (start, tower), (end, _) in zip(rows, rows[1:], strict=False):
            if start < -1440 and is_weekend(start) and tower in malls and tower != homes[sub]:
                lengths.append(end - start)
    assert lengths and all(120 <= n <= 240 for n in lengths)


def test_movers_without_a_mall_in_range_never_move_on_weekends(conn: sqlite3.Connection) -> None:
    homes = _homes(conn)
    movers_on_weekends = {
        sub
        for sub, rows in _visits(conn).items()
        if any(minute < -1440 and is_weekend(minute) and tower != homes[sub] for minute, tower in rows)
    }
    assert movers_on_weekends
    assert all(_mall_in_range(conn, homes[sub]) for sub in movers_on_weekends)


def test_the_default_seed_has_plenty_of_weekend_mall_visitors(tmp_path: Path) -> None:
    db = tmp_path / "full.db"
    build(db, load_scenario(settings.default_scenario_path()), towers=DEFAULT_TOWER_COUNT)
    with sqlite3.connect(db) as raw:
        raw.row_factory = sqlite3.Row
        days = _weekend_mall_days(raw)
        homes = _homes(raw)
        in_range_movers = {
            sub
            for sub, rows in _visits(raw).items()
            if len({t for _, t in rows}) > 1 and _mall_in_range(raw, homes[sub])
        }
        assert in_range_movers and len(set(days) & in_range_movers) / len(in_range_movers) >= 0.25
        assert raw.execute("SELECT MAX(start_min) FROM subscriber_cell_visit").fetchone()[0] <= 480
