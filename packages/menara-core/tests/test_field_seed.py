"""Synthetic field workforce: fictional technicians at the drone depots, their skills and shifts, and spare parts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db

SKILLS = {"POWER", "RAN", "FIBRE", "CIVIL"}
PARTS = {"GENERATOR", "RECTIFIER", "BATTERY", "ANTENNA"}


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("field"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_there_are_about_30_technicians_at_the_drone_depots_with_fictional_names(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM technician").fetchall()
    depots = {r["depot_id"] for r in conn.execute("SELECT DISTINCT depot_id FROM drone")}
    assert len(rows) == 30 and {r["depot_id"] for r in rows} == depots
    assert all(r["name"].endswith("(synthetic)") for r in rows) and len({r["name"] for r in rows}) == len(rows)


def test_skills_and_shifts_are_valid_and_every_depot_has_power_and_a_day_shift(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM technician").fetchall()
    assert all(set(r["skills"].split(",")) <= SKILLS and r["skills"] for r in rows)
    assert all(0 <= r["shift_start_hour"] <= 23 and 0 <= r["shift_end_hour"] <= 23 for r in rows)
    for depot in {r["depot_id"] for r in rows}:
        mine = [r for r in rows if r["depot_id"] == depot]
        assert any("POWER" in r["skills"].split(",") for r in mine)
        assert any(r["shift_start_hour"] == 6 and r["shift_end_hour"] == 18 for r in mine)


def test_technicians_start_at_their_depot(conn: sqlite3.Connection) -> None:
    depots = {r["depot_id"]: (r["lat"], r["lng"]) for r in conn.execute("SELECT DISTINCT depot_id, lat, lng FROM drone")}
    for r in conn.execute("SELECT * FROM technician"):
        assert (r["lat"], r["lng"]) == depots[r["depot_id"]]


def test_spare_parts_exist_per_depot_and_the_kota_bharu_depot_has_a_generator_and_batteries(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM spare_part").fetchall()
    assert {r["part"] for r in rows} == PARTS and all(0 <= r["qty"] <= 6 for r in rows)
    kb = {r["part"]: r["qty"] for r in rows if r["depot_id"] == "DEP-KTBH"}
    assert kb["GENERATOR"] >= 1 and kb["BATTERY"] >= 2


def test_the_job_table_starts_empty_and_the_seed_is_repeatable(conn: sqlite3.Connection, db_file: Path, tmp_path: Path) -> None:
    assert conn.execute("SELECT COUNT(*) FROM field_job").fetchone()[0] == 0
    other = build_test_db(tmp_path)
    with sqlite3.connect(other) as b:
        assert [tuple(r) for r in conn.execute("SELECT * FROM technician ORDER BY 1")] == b.execute("SELECT * FROM technician ORDER BY 1").fetchall()