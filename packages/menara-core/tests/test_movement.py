"""Subscriber trails: cell-to-cell movement over the seeded period (synthetic)."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core import settings
from menara_core.geo import haversine_km
from menara_core.scenario import load_scenario
from menara_core.seed.build import DEFAULT_TOWER_COUNT
from menara_core.testing import build_test_db

# Row count and a short hash of every row, recorded from `main` before movement existed.
# If one of these changes, the seed's main random stream was disturbed.
BASELINE = {
    "subscriber": (932, "ad3b9c4412d4"),
    "subscriber_state": (1012, "67d940fb5ba5"),
    "subscriber_experience": (71044, "73f71a82e048"),
    "ticket": (49, "ccc07a53185c"),
    "tower": (57, "31cb1a6779a4"),
    "tower_subscribers": (57, "4fed313ce4e3"),
    "critical_site": (214, "90b0ddb4172c"),
    "tower_kpi": (3069, "5bc2003d20c2"),
}


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("movement"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def cluster_towers() -> set[str]:
    return {t.enodeb for t in load_scenario(settings.default_scenario_path()).cluster.towers}


def test_old_tables_are_unchanged_by_movement(conn: sqlite3.Connection) -> None:
    for table, expected in BASELINE.items():
        rows = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()]
        where = " WHERE kind != 'MALL'" if table == "critical_site" else ""  # malls are new rows, not changed ones
        rows = [tuple(r) for r in conn.execute(f"SELECT * FROM {table}{where} ORDER BY 1,2").fetchall()]
        assert (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:12]) == expected, table


def test_every_subscriber_is_where_the_subscriber_table_says_at_minute_0(conn: sqlite3.Connection) -> None:
    mismatched = conn.execute(
        """
        SELECT s.msisdn_hash FROM subscriber s
        WHERE s.serving_cell IS NOT (
            SELECT v.serving_cell FROM subscriber_cell_visit v
            WHERE v.msisdn_hash = s.msisdn_hash AND v.start_min <= 0 ORDER BY v.start_min DESC LIMIT 1)
        """
    ).fetchall()
    assert mismatched == []
    assert conn.execute("SELECT COUNT(DISTINCT msisdn_hash) FROM subscriber_cell_visit").fetchone()[0] == 932


def test_visits_start_at_the_beginning_and_stay_in_the_seeded_period(conn: sqlite3.Connection) -> None:
    firsts = conn.execute("SELECT MIN(start_min) AS first FROM subscriber_cell_visit GROUP BY msisdn_hash").fetchall()
    assert {r["first"] for r in firsts} == {-40320}  # four weeks before T0
    assert conn.execute("SELECT MAX(start_min) FROM subscriber_cell_visit").fetchone()[0] <= 480


def test_cluster_subscribers_never_move(conn: sqlite3.Connection) -> None:
    names = ",".join(f"'{n}'" for n in cluster_towers())
    rows = conn.execute(
        f"""
        SELECT COUNT(*) AS visits FROM subscriber_cell_visit
        WHERE msisdn_hash IN (SELECT msisdn_hash FROM subscriber WHERE enodeb_name IN ({names}))
        GROUP BY msisdn_hash
        """
    ).fetchall()
    assert rows and {r["visits"] for r in rows} == {1}


def test_at_least_30_percent_of_the_other_subscribers_move_between_existing_towers(conn: sqlite3.Connection) -> None:
    names = ",".join(f"'{n}'" for n in cluster_towers())
    others = conn.execute(f"SELECT COUNT(*) FROM subscriber WHERE enodeb_name NOT IN ({names})").fetchone()[0]
    movers = conn.execute(
        f"""
        SELECT COUNT(*) FROM (
            SELECT msisdn_hash FROM subscriber_cell_visit
            WHERE msisdn_hash IN (SELECT msisdn_hash FROM subscriber WHERE enodeb_name NOT IN ({names}))
            GROUP BY msisdn_hash HAVING COUNT(DISTINCT enodeb_name) > 1)
        """
    ).fetchone()[0]
    assert movers / others >= 0.30
    unknown = conn.execute(
        "SELECT COUNT(*) FROM subscriber_cell_visit v LEFT JOIN cell c ON c.cell_id = v.serving_cell "
        "WHERE c.cell_id IS NULL OR c.enodeb_name != v.enodeb_name"
    ).fetchone()[0]
    assert unknown == 0


def test_commuters_stop_at_a_tower_between_home_and_work(conn: sqlite3.Connection) -> None:
    coords = {r["enodeb_name"]: (r["lat"], r["lng"]) for r in conn.execute("SELECT enodeb_name, lat, lng FROM tower")}
    home = {r["msisdn_hash"]: r["enodeb_name"] for r in conn.execute("SELECT msisdn_hash, enodeb_name FROM subscriber")}
    visits: dict[str, list[tuple[int, str]]] = {}
    for r in conn.execute("SELECT msisdn_hash, start_min, enodeb_name FROM subscriber_cell_visit ORDER BY msisdn_hash, start_min"):
        visits.setdefault(r["msisdn_hash"], []).append((r["start_min"], r["enodeb_name"]))
    on_the_way = 0
    for sub, trail in visits.items():
        if len({tower for _, tower in trail}) < 2:
            continue
        work = trail[-1][1]
        assert work != home[sub]
        assert 5.0 <= haversine_km(*coords[home[sub]], *coords[work]) <= 25.0
        today = [tower for start, tower in trail if start >= 0]
        assert today and today[-1] == work and trail[0][1] == home[sub]
        if len(today) == 2:  # a tower on the way, then work
            on_the_way += 1
            assert today[0] not in (home[sub], work)
    assert on_the_way > 0


def test_the_same_seed_gives_the_same_trails(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    query = "SELECT * FROM subscriber_cell_visit ORDER BY msisdn_hash, start_min"
    a, b = sqlite3.connect(db_file), sqlite3.connect(other)
    try:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()
    finally:
        a.close()
        b.close()


def test_location_is_cell_level(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT v.cell_lat, v.cell_lng, t.lat, t.lng FROM subscriber_cell_visit v JOIN tower t ON t.enodeb_name = v.enodeb_name LIMIT 1"
    ).fetchone()
    assert (row["cell_lat"], row["cell_lng"]) == (round(row["lat"], 3), round(row["lng"], 3))

def test_the_default_seed_has_plenty_of_commuters(tmp_path: Path) -> None:
    """The demo uses the full-size seed, where towns are dense; the small test seed is not enough to prove this."""
    db = build_test_db(tmp_path, towers=DEFAULT_TOWER_COUNT, seed=42)
    connection = sqlite3.connect(db)
    try:
        total = connection.execute("SELECT COUNT(*) FROM subscriber").fetchone()[0]
        movers = connection.execute(
            "SELECT COUNT(*) FROM (SELECT msisdn_hash FROM subscriber_cell_visit GROUP BY msisdn_hash "
            "HAVING COUNT(DISTINCT enodeb_name) > 1)"
        ).fetchone()[0]
    finally:
        connection.close()
    assert movers / total >= 0.30