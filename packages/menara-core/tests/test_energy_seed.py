"""Synthetic tower energy: power draw, battery and generator, per tower. Invented numbers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("energy"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_every_tower_has_an_energy_row(conn: sqlite3.Connection) -> None:
    towers = conn.execute("SELECT COUNT(*) FROM tower").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM tower_energy").fetchone()[0] == towers


def test_ranges_are_sane_and_towers_without_a_generator_have_no_fuel(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM tower_energy").fetchall()
    assert all(0.5 <= r["base_kw"] <= 6.0 and 2.0 <= r["battery_kwh"] <= 30.0 for r in rows)
    with_gen = [r for r in rows if r["has_genset"]]
    without = [r for r in rows if not r["has_genset"]]
    assert 0 < len(with_gen) < len(rows) and without
    assert all(r["genset_fuel_l"] > 0 and r["genset_l_per_h"] > 0 for r in with_gen)
    assert all(r["genset_fuel_l"] == 0 and r["genset_l_per_h"] == 0 for r in without)


def test_a_bigger_tower_type_draws_more(conn: sqlite3.Connection) -> None:
    by_type = {
        r["tower_type"]: r["avg_kw"]
        for r in conn.execute(
            "SELECT t.tower_type, AVG(e.base_kw) AS avg_kw FROM tower t JOIN tower_energy e ON e.enodeb_name = t.enodeb_name GROUP BY t.tower_type"
        )
    }
    assert by_type["macro"] > by_type["rooftop"] > by_type["pole"]


def test_the_flooded_tower_has_a_generator_with_limited_fuel(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT * FROM tower_energy WHERE enodeb_name = 'KKRI-0142'").fetchone()
    assert row["has_genset"] == 1
    assert 5.0 <= row["genset_fuel_l"] / row["genset_l_per_h"] <= 12.0  # hours of fuel


def test_same_seed_same_energy(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    query = "SELECT * FROM tower_energy ORDER BY 1"
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()


def test_the_energy_action_table_starts_empty(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT COUNT(*) FROM energy_action").fetchone()[0] == 0