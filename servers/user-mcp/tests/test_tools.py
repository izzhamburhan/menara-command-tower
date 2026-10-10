from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from user_mcp import tools


def _anchor_customer(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT customer_ref FROM ticket WHERE ticket_id = 'TK-88213'").fetchone()
    return str(row["customer_ref"])


def test_flooded_customer_is_on_the_flooded_cell(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    env = tools.get_serving_cell(conn, _anchor_customer(conn))
    assert env.synthetic is True
    assert env.data.serving_cell == "KKRI-0142-B1"
    assert env.data.enodeb_name == "KKRI-0142"
    assert env.data.attached is False
    assert env.data.detached_since is not None and env.data.detached_since.startswith("2026-11-14T06:55")
    assert env.warnings


def test_same_customer_was_attached_before_the_outage(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(-100)
    assert tools.get_serving_cell(conn, _anchor_customer(conn)).data.attached is True


def test_location_is_cell_level_and_pii_is_masked(conn: sqlite3.Connection) -> None:
    data = tools.get_serving_cell(conn, _anchor_customer(conn)).data
    assert data.location_precision == "cell"
    assert (data.cell_lat, data.cell_lng) == (5.531, 102.197)
    dumped = data.model_dump_json()
    assert "+60" not in dumped and "msisdn\"" not in dumped
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    columns = {r[1] for t in tables for r in conn.execute(f"PRAGMA table_info({t})")}
    assert "msisdn" not in columns


def test_experience_collapses_when_the_tower_goes_down(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    customer = _anchor_customer(conn)
    set_clock(-60)
    before = tools.get_experience(conn, customer, window_min=30).data
    assert before.latest is not None and before.latest.label in {"GOOD", "FAIR"}
    set_clock(12)
    after = tools.get_experience(conn, customer, window_min=30).data
    assert after.latest is not None and after.latest.label == "NO_SERVICE"
    assert after.summary.worst_label == "NO_SERVICE"
    assert after.latest.throughput_mbps == 0.0


def test_overloaded_neighbour_customers_are_degraded_not_silent(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    row = conn.execute("SELECT msisdn_hash FROM subscriber WHERE enodeb_name = 'KKRI-0143' LIMIT 1").fetchone()
    latest = tools.get_experience(conn, row["msisdn_hash"], window_min=30).data.latest
    assert latest is not None and latest.label != "NO_SERVICE"


def test_experience_window_without_samples_falls_back_to_latest(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    row = conn.execute("SELECT msisdn_hash FROM subscriber WHERE enodeb_name NOT LIKE 'KKRI-%' LIMIT 1").fetchone()
    set_clock(110)
    env = tools.get_experience(conn, row["msisdn_hash"], window_min=5)
    assert env.data.points == [] and env.data.latest is not None and env.warnings
    assert env.data.summary.avg_score is None


def test_label_thresholds() -> None:
    assert tools.label_for(0.0, 0.0) == "NO_SERVICE"
    assert tools.label_for(10.0, 2.0) == "POOR"
    assert tools.label_for(55.0, 20.0) == "FAIR"
    assert tools.label_for(90.0, 40.0) == "GOOD"


def test_validation_and_unknown_subscriber(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_serving_cell(conn, "+60123456789")
    with pytest.raises(NotFoundError):
        tools.get_serving_cell(conn, "0" * 16)
    with pytest.raises(InvalidInputError):
        tools.get_experience(conn, _anchor_customer(conn), window_min=1)
