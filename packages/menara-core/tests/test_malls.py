"""Synthetic malls: one per town, as ordinary (non-emergency) sites that a subscriber's weekend routine can point at."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core import settings
from menara_core.scenario import load_scenario
from menara_core.testing import build_test_db

# Count and short hash of every critical_site row that is not a mall, recorded from `main` before malls existed.
OLD_SITES = (214, "90b0ddb4172c")


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("malls"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def _malls(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM critical_site WHERE kind = 'MALL' ORDER BY critical_site_id").fetchall()


def _towns(conn: sqlite3.Connection, kind_filter: str) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            f"SELECT DISTINCT t.town FROM critical_site s JOIN tower t ON t.enodeb_name = s.serving_enodeb WHERE {kind_filter} ORDER BY 1"
        )
    ]


def test_every_town_with_generated_sites_has_exactly_one_mall(conn: sqlite3.Connection) -> None:
    malls = _malls(conn)
    assert malls
    per_town = conn.execute(
        "SELECT t.town, COUNT(*) AS n FROM critical_site s JOIN tower t ON t.enodeb_name = s.serving_enodeb "
        "WHERE s.kind = 'MALL' GROUP BY t.town"
    ).fetchall()
    assert {r["n"] for r in per_town} == {1}
    cluster = ", ".join(f"'{t.enodeb}'" for t in load_scenario(settings.default_scenario_path()).cluster.towers)
    with_sites = set(_towns(conn, f"s.kind != 'MALL' AND s.serving_enodeb NOT IN ({cluster})"))
    assert with_sites <= set(_towns(conn, "s.kind = 'MALL'"))


def test_a_mall_is_not_an_emergency_site_and_has_priority_4(conn: sqlite3.Connection) -> None:
    malls = _malls(conn)
    assert malls and {(m["priority"], m["emergency_service"]) for m in malls} == {(4, 0)}


def test_a_mall_is_served_by_a_non_cluster_tower_of_its_own_town(conn: sqlite3.Connection) -> None:
    cluster = {t.enodeb for t in load_scenario(settings.default_scenario_path()).cluster.towers}
    malls = _malls(conn)
    assert malls
    for mall in malls:
        assert mall["serving_enodeb"] not in cluster
        town = conn.execute("SELECT town FROM tower WHERE enodeb_name = ?", (mall["serving_enodeb"],)).fetchone()["town"]
        assert mall["name"].startswith(f"{town} Mall ")


def test_mall_names_say_synthetic(conn: sqlite3.Connection) -> None:
    malls = _malls(conn)
    assert malls and all(m["name"].endswith("(synthetic)") for m in malls)


def test_the_other_site_rows_are_unchanged(conn: sqlite3.Connection) -> None:
    rows = [tuple(r) for r in conn.execute("SELECT * FROM critical_site WHERE kind != 'MALL' ORDER BY 1,2").fetchall()]
    assert (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:12]) == OLD_SITES


def test_malls_are_the_same_for_the_same_seed(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    query = "SELECT * FROM critical_site WHERE kind = 'MALL' ORDER BY 1"
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()