"""Synthetic business customers: fictional companies with an SLA, on specific towers. Invented numbers."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("enterprise"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_every_enterprise_site_has_an_account_and_names_say_synthetic(conn: sqlite3.Connection) -> None:
    sites = {r["serving_enodeb"] for r in conn.execute("SELECT serving_enodeb FROM critical_site WHERE kind = 'ENTERPRISE'")}
    served = {r["enodeb_name"] for r in conn.execute("SELECT enodeb_name FROM enterprise_account")}
    assert sites and sites <= served
    names = [r["name"] for r in conn.execute("SELECT name FROM enterprise_account")]
    assert names and all(n.endswith("(synthetic)") for n in names) and len(set(names)) == len(names)


def test_the_flooded_tower_serves_two_accounts_and_the_cluster_has_more(conn: sqlite3.Connection) -> None:
    on_flood = conn.execute("SELECT COUNT(*) FROM enterprise_account WHERE enodeb_name = 'KKRI-0142'").fetchone()[0]
    in_cluster = conn.execute("SELECT COUNT(*) FROM enterprise_account WHERE enodeb_name LIKE 'KKRI-%'").fetchone()[0]
    assert on_flood == 2 and in_cluster >= 5


def test_account_fields_are_in_range_and_consistent(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT * FROM enterprise_account"):
        assert r["account_id"].startswith("ACC-") and r["plan"] and r["sector"]
        assert 2000 <= r["monthly_value_rm"] <= 60000
        assert r["sla_availability_pct"] in (99.5, 99.9, 99.95)
        assert r["penalty_rm_per_hour"] == pytest.approx(r["monthly_value_rm"] * 0.01, rel=0.01)
        assert conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (r["enodeb_name"],)).fetchone()


def test_the_credit_table_starts_empty(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT COUNT(*) FROM sla_credit").fetchone()[0] == 0


def test_same_seed_same_accounts(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    query = "SELECT * FROM enterprise_account ORDER BY 1"
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()