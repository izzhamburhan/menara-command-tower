"""Reset: put the demo back to a clean state (what agents and people created is removed, defaults restored)."""

from __future__ import annotations

import hashlib
import io
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core import clock, settings
from menara_core.db import connect
from menara_core.errors import DatabaseNotSeededError
from menara_core.reset import RUNTIME_TABLES, reset_runtime_state
from menara_core.scenario import Scenario, load_scenario
from menara_core.scenario_cli import main as scenario_main
from menara_core.seed.actions import policy_settings
from menara_core.testing import build_test_db

BASE_TABLES = ("tower", "subscriber", "subscriber_cell_visit", "ticket", "critical_site", "seed_meta", "ran_script", "drone")
AT = "2026-11-14T07:12:00+08:00"


@pytest.fixture
def scenario() -> Scenario:
    return load_scenario(settings.default_scenario_path())


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return build_test_db(tmp_path)


def writer(db_file: Path) -> sqlite3.Connection:
    return connect(db_file, owned_tables=set(RUNTIME_TABLES) | {"policy_setting", "scenario_state"})


def dirty(db_file: Path) -> None:
    """Add one row to every runtime table, change a policy setting and move the clock, as a long session would."""
    conn = writer(db_file)
    try:
        conn.execute(
            "INSERT INTO incident (incident_id, enodeb_name, cause, cause_confidence, summary, status, created_at, updated_at, evidence) "
            "VALUES ('INC-0001', 'KKRI-0142', 'FLOOD', 0.9, 's', 'OPEN', ?, ?, '[]')", (AT, AT)
        )
        ticket = conn.execute("SELECT ticket_id FROM ticket ORDER BY ticket_id LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO incident_ticket VALUES ('INC-0001', ?)", (ticket,))
        conn.execute("INSERT INTO twin_simulation (sim_id, kind, at, params, result) VALUES ('SIM-0001', 'tilt', ?, '{}', '{}')", (AT,))
        conn.execute(
            "INSERT INTO ran_change (change_id, action, status, applied_min, applied_at, approved_by, reason) "
            "VALUES ('CHG-0001', 'ran_tilt_cells', 'ACTIVE', 12, ?, 'human', 'r')", (AT,)
        )
        cell = conn.execute("SELECT cell_id FROM cell WHERE enodeb_name = 'KKRI-0143' LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO ran_change_item VALUES ('CHG-0001', 'KKRI-0143', ?, 4.0, 0.1, 1)", (cell,))
        conn.execute("INSERT INTO ran_kpi_effect VALUES ('CHG-0001', 'KKRI-0143', 12, 0.9, 0.9, 1.1)")
        drone = conn.execute("SELECT drone_id FROM drone LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO drone_mission (mission_id, drone_id, enodeb_name, dispatched_min, dispatched_at, distance_km, eta_min, inspect_min, approved_by, reason) "
            "VALUES ('MIS-0001', ?, 'KKRI-0142', 12, ?, 50.0, 33, 15, 'human', 'r')", (drone, AT)
        )
        conn.execute(
            "INSERT INTO approval (approval_id, action, target, status, confidence, affected_subscribers, touches_emergency, reason, requested_min, requested_at) "
            "VALUES ('APR-0001', 'drone_dispatch', 'KKRI-0142', 'PENDING', 0.9, 10, 0, 'r', 12, ?)", (AT,)
        )
        conn.execute("INSERT INTO audit_log (at, actor, action, target, decision, detail) VALUES (?, 'agent', 'a', 't', 'ask', 'd')", (AT,))
        conn.execute("INSERT INTO ticket_note (ticket_id, at, author, text) VALUES (?, ?, 'agent', 'n')", (ticket, AT))
        conn.execute("INSERT INTO ticket_resolution VALUES (?, 20, ?, 'agent', 'done')", (ticket, AT))
        conn.execute(
            "INSERT INTO energy_action (action_id, enodeb_name, kind, from_min, to_min, kwh_saved, co2_kg_saved, approved_by, reason) "
            "VALUES ('ENA-0001', 'KKRI-0143', 'SLEEP', 1200, 1560, 3.0, 1.75, 'human', 'r')"
        )
        conn.execute("UPDATE policy_setting SET value = '1' WHERE key = 'kill_switch'")
        conn.execute("UPDATE policy_setting SET value = '999' WHERE key = 'auto_allow_max_subscribers'")
        conn.commit()
        clock.set_now(conn, 377)
    finally:
        conn.close()


def base_fingerprint(db_file: Path) -> dict[str, tuple[int, str]]:
    conn = sqlite3.connect(db_file)
    try:
        out = {}
        for table in BASE_TABLES:
            rows = [tuple(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()]
            out[table] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest()[:12])
        return out
    finally:
        conn.close()


def count(db_file: Path, table: str) -> int:
    conn = sqlite3.connect(db_file)
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


@pytest.fixture
def played(db_file: Path) -> Iterator[Path]:
    dirty(db_file)
    yield db_file


def test_reset_clears_every_runtime_table_and_reports_the_counts(played: Path, scenario: Scenario) -> None:
    before = {t: count(played, t) for t in RUNTIME_TABLES}
    assert all(n >= 1 for n in before.values())
    deleted = reset_runtime_state(played, scenario)
    assert deleted == before
    assert all(count(played, t) == 0 for t in RUNTIME_TABLES)


def test_the_runtime_tables_are_exactly_the_ones_servers_write(played: Path) -> None:
    assert set(RUNTIME_TABLES) == {
        "incident", "incident_ticket", "twin_simulation", "ran_change", "ran_change_item", "ran_kpi_effect",
        "drone_mission", "approval", "audit_log", "ticket_note", "ticket_resolution", "energy_action",
    }


def test_the_next_ids_start_again_from_one(played: Path, scenario: Scenario) -> None:
    reset_runtime_state(played, scenario)
    conn = writer(played)
    try:
        conn.execute(
            "INSERT INTO incident (incident_id, enodeb_name, cause, cause_confidence, summary, status, created_at, updated_at, evidence) "
            "VALUES ('INC-X', 'KKRI-0142', 'FLOOD', 0.9, 's', 'OPEN', ?, ?, '[]')", (AT, AT)
        )
        conn.execute("INSERT INTO audit_log (at, actor, action, target, decision, detail) VALUES (?, 'a', 'a', 't', 'allow', 'd')", (AT,))
        conn.commit()
        assert conn.execute("SELECT seq FROM incident").fetchone()[0] == 1
        assert conn.execute("SELECT id FROM audit_log").fetchone()[0] == 1
    finally:
        conn.close()


def test_policy_settings_go_back_to_the_scenario_defaults(played: Path, scenario: Scenario) -> None:
    reset_runtime_state(played, scenario)
    conn = sqlite3.connect(played)
    try:
        assert dict(conn.execute("SELECT key, value FROM policy_setting").fetchall()) == policy_settings(scenario)
    finally:
        conn.close()


def test_the_clock_goes_back_to_the_default(played: Path, scenario: Scenario) -> None:
    reset_runtime_state(played, scenario)
    conn = connect(played)
    try:
        assert clock.now_min(conn) == scenario.default_now_min
    finally:
        conn.close()


def test_base_tables_are_untouched(played: Path, scenario: Scenario) -> None:
    before = base_fingerprint(played)
    reset_runtime_state(played, scenario)
    assert base_fingerprint(played) == before


def test_a_failure_leaves_everything_as_it_was(played: Path, scenario: Scenario, monkeypatch: pytest.MonkeyPatch) -> None:
    import menara_core.reset as reset_module

    original = reset_module.policy_settings

    def boom(_: Scenario) -> dict[str, str]:
        raise RuntimeError("disk full")

    monkeypatch.setattr(reset_module, "policy_settings", boom)
    before = {t: count(played, t) for t in RUNTIME_TABLES}
    with pytest.raises(RuntimeError):
        reset_runtime_state(played, scenario)
    monkeypatch.setattr(reset_module, "policy_settings", original)
    assert {t: count(played, t) for t in RUNTIME_TABLES} == before
    conn = connect(played)
    try:
        assert clock.now_min(conn) == 377
    finally:
        conn.close()


def test_reset_of_a_missing_database_says_not_seeded(tmp_path: Path, scenario: Scenario) -> None:
    with pytest.raises(DatabaseNotSeededError):
        reset_runtime_state(tmp_path / "nope.db", scenario)


def test_the_seed_and_the_reset_use_the_same_policy_defaults(db_file: Path, scenario: Scenario) -> None:
    conn = sqlite3.connect(db_file)
    try:
        assert dict(conn.execute("SELECT key, value FROM policy_setting").fetchall()) == policy_settings(scenario)
    finally:
        conn.close()


def test_the_cli_needs_yes_and_prints_the_counts(played: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # not a terminal
    assert scenario_main(["reset-state", "--db", str(played)]) == 2
    assert count(played, "incident") == 1  # nothing was removed
    assert scenario_main(["reset-state", "--yes", "--db", str(played)]) == 0
    out = capsys.readouterr().out
    assert "incident" in out and "1" in out
    assert count(played, "incident") == 0