"""Synthetic scam signals: generic patterns and hourly counts per town. Counts only: no number, sender or recipient."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("scam"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_there_are_ten_generic_patterns_with_valid_kinds_and_severity(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT * FROM scam_pattern").fetchall()
    assert len(rows) == 10 and {r["kind"] for r in rows} == {"VOICE", "SMS", "MESSAGING"}
    assert {r["severity"] for r in rows} <= {"LOW", "MEDIUM", "HIGH"} and {"LOW", "HIGH"} <= {r["severity"] for r in rows}
    assert all(r["name"].endswith("(synthetic)") and r["example"] and r["advice"] for r in rows)


def test_patterns_carry_no_number_link_or_brand(conn: sqlite3.Connection) -> None:
    for r in conn.execute("SELECT * FROM scam_pattern"):
        text = " ".join(str(v) for v in dict(r).values())
        assert not re.search(r"\d{5,}", text) and "http" not in text.lower() and "www." not in text.lower()
        assert "telekom" not in text.lower() and "unifi" not in text.lower()


def test_signals_are_hourly_counts_per_pattern_and_town(conn: sqlite3.Connection) -> None:
    times = {r["t_min"] for r in conn.execute("SELECT DISTINCT t_min FROM scam_signal")}
    assert min(times) == -1440 and max(times) == 720 and all(t % 60 == 0 for t in times)
    row = conn.execute("SELECT MIN(reports) AS lo, MAX(reports) AS hi, MIN(blocked) AS blo FROM scam_signal").fetchone()
    assert row["lo"] >= 0 and row["hi"] > 5 and row["blo"] >= 0
    columns = [r["name"] for r in conn.execute("PRAGMA table_info(scam_signal)")]
    assert columns == ["pattern_id", "town", "t_min", "reports", "blocked"]  # counts only: nothing that identifies a person


def test_a_flood_relief_scam_rises_in_the_flood_region_around_t0(conn: sqlite3.Connection) -> None:
    pattern = conn.execute("SELECT pattern_id FROM scam_pattern WHERE name LIKE '%flood%'").fetchone()["pattern_id"]

    def reports(start: int, end: int) -> int:
        return int(conn.execute("SELECT SUM(reports) FROM scam_signal WHERE pattern_id = ? AND town = 'Kuala Krai' AND t_min BETWEEN ? AND ?", (pattern, start, end)).fetchone()[0])

    assert reports(-120, 120) > 3 * reports(-1440, -1200)


def test_same_seed_same_signals(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        for query in ("SELECT * FROM scam_pattern ORDER BY 1", "SELECT * FROM scam_signal ORDER BY 1, 2, 3"):
            assert a.execute(query).fetchall() == b.execute(query).fetchall()