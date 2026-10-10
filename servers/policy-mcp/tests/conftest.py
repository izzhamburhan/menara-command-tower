from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from menara_core import clock, settings
from menara_core.db import connect
from menara_core.testing import build_test_db
from policy_mcp.tools import OWNED_TABLES

DEFAULTS = {
    "kill_switch": "0",
    "auto_allow_max_subscribers": "500",
    "auto_allow_min_confidence": "0.9",
    "peak_start_hour": "18",
    "peak_end_hour": "23",
    "max_actions_per_hour": "10",
    "token_ttl_s": "300",
}


@pytest.fixture(scope="session")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("policy-db"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(db_file, owned_tables=OWNED_TABLES)
    yield connection
    connection.execute("DELETE FROM approval")
    connection.execute("DELETE FROM audit_log")
    for key, value in DEFAULTS.items():
        connection.execute("UPDATE policy_setting SET value = ? WHERE key = ?", (value, key))
    connection.commit()
    connection.close()


@pytest.fixture
def set_clock(db_file: Path) -> Iterator[Callable[[int], None]]:
    """Move the scenario clock for one test; always restored to T0 afterwards."""
    writer = connect(db_file, owned_tables={"scenario_state"})

    def move(minutes: int) -> None:
        clock.set_now(writer, minutes)

    yield move
    clock.set_now(writer, 0)
    writer.close()


@pytest.fixture
def human_key() -> str:
    return settings.approver_key()


@pytest.fixture
def quiet_tower(conn: sqlite3.Connection) -> str:
    """A non-scenario tower with no emergency site. Its subscriber count is below the auto-allow limit."""
    row = conn.execute(
        "SELECT t.enodeb_name, s.subscribers_est FROM tower t JOIN tower_subscribers s ON s.enodeb_name = t.enodeb_name "
        "WHERE t.enodeb_name NOT LIKE 'KKRI-%' AND NOT EXISTS ("
        "SELECT 1 FROM critical_site c WHERE c.serving_enodeb = t.enodeb_name AND c.emergency_service = 1) "
        "ORDER BY s.subscribers_est, t.enodeb_name LIMIT 1"
    ).fetchone()
    assert row is not None, "test database has no tower without an emergency site"
    conn.execute(
        "UPDATE policy_setting SET value = ? WHERE key = 'auto_allow_max_subscribers'",
        (str(int(row["subscribers_est"]) + 1),),
    )
    conn.commit()
    return str(row["enodeb_name"])
