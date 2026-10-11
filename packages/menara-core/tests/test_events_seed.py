"""Synthetic crowd events: fictional festivals, matches, concerts and the balik kampung rush, with their crowd sizes."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.crowd import PRB_POINTS_PER_ATTENDEE, serving_towers, uplift_by_tower
from menara_core.testing import build_test_db

KINDS = {"FESTIVAL", "MATCH", "CONCERT", "EXODUS"}


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("events"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_there_are_about_25_events_with_fictional_names_and_valid_kinds(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM crowd_event").fetchall()
    assert 20 <= len(rows) <= 32 and {r["kind"] for r in rows} <= KINDS and len({r["kind"] for r in rows}) >= 3
    assert all(r["name"].endswith("(synthetic)") for r in rows) and len({r["name"] for r in rows}) == len(rows)


def test_every_event_is_in_the_future_and_ends_after_it_starts(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT * FROM crowd_event"):
        assert 120 <= r["start_min"] <= 6000 and r["end_min"] > r["start_min"]
        assert 1000 <= r["attendance"] <= 120000 and 0.3 <= r["radius_km"] <= 5.0


def test_events_sit_next_to_towers(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT * FROM crowd_event"):
        nearest = serving_towers(conn, r["lat"], r["lng"], 1)[0]
        assert nearest[1] < 5.0


def test_a_scripted_derby_in_kota_bharu_is_the_next_big_match(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT * FROM crowd_event WHERE name LIKE 'Kota Bharu Derby%'").fetchone()
    assert row is not None and row["kind"] == "MATCH" and row["attendance"] >= 30000


def test_the_crowd_model_spreads_the_attendance_over_the_nearest_towers(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT * FROM crowd_event WHERE name LIKE 'Kota Bharu Derby%'").fetchone()
    uplift = uplift_by_tower(conn, row)
    assert len(uplift) == 5 and abs(sum(uplift.values()) - row["attendance"] * PRB_POINTS_PER_ATTENDEE) < 0.5
    near = serving_towers(conn, row["lat"], row["lng"], 5)
    assert uplift[near[0][0]] == max(uplift.values())  # the closest tower takes the most


def test_same_seed_same_events(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    query = "SELECT * FROM crowd_event ORDER BY 1"
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()