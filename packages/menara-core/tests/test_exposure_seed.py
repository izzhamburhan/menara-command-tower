"""Synthetic network-exposure products: quality-on-demand profiles with a price and the capacity they reserve."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("exposure"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_four_profiles_with_prices_and_headroom_needs(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM qod_profile ORDER BY profile_id").fetchall()
    assert [r["profile_id"] for r in rows] == ["AR_EXPERIENCE", "BROADCAST_UPLINK", "ESPORTS_LOW_LATENCY", "FLEET_TELEMATICS"]
    assert all(r["price_rm_per_hour_per_tower"] > 0 and 1 <= r["headroom_prb"] <= 30 and r["guaranteed"] and r["description"] for r in rows)
    by_id = {r["profile_id"]: r for r in rows}
    assert by_id["BROADCAST_UPLINK"]["price_rm_per_hour_per_tower"] > by_id["FLEET_TELEMATICS"]["price_rm_per_hour_per_tower"]


def test_descriptions_make_no_real_world_claims(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT * FROM qod_profile"):
        assert "synthetic" in r["description"].lower()


def test_the_booking_table_starts_empty(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT COUNT(*) FROM qod_booking").fetchone()[0] == 0