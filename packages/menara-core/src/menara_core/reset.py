"""Reset the demo: remove what agents and people created and put the defaults back, with the servers still running.

This is a maintenance helper like the seed, not an MCP tool: no agent can reach it. It is the one place that writes
tables owned by several servers, and it only runs when a person asks (the demo's Reset button or `menara-scenario
reset-state`). Base tables are never touched. All data is synthetic.
"""

from __future__ import annotations

from pathlib import Path

from menara_core import clock
from menara_core.db import connect
from menara_core.scenario import Scenario
from menara_core.seed.actions import policy_settings

# Children first, so a foreign key never blocks a delete.
RUNTIME_TABLES: tuple[str, ...] = (
    "incident_ticket",
    "incident",
    "twin_simulation",
    "ran_kpi_effect",
    "ran_change_item",
    "ran_change",
    "drone_mission",
    "approval",
    "audit_log",
    "ticket_note",
    "ticket_resolution",
    "energy_action",
    "care_notice",
    "sla_credit",
    "qod_booking",
    "field_job",
    "ntt_ctt_link",
    "ntt_note",
    "ntt",
)


def reset_runtime_state(db_path: Path, scenario: Scenario) -> dict[str, int]:
    """Delete every runtime row, restart the id counters, restore policy defaults and the clock. All or nothing."""
    conn = connect(db_path, owned_tables={*RUNTIME_TABLES, "policy_setting", "scenario_state", "sqlite_sequence"})
    try:
        with conn:  # one transaction: commit on success, roll back on any error
            deleted = {table: conn.execute(f"DELETE FROM {table}").rowcount for table in RUNTIME_TABLES}
            marks = ", ".join("?" for _ in RUNTIME_TABLES)
            conn.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({marks})", RUNTIME_TABLES)
            defaults = policy_settings(scenario)
            conn.execute("DELETE FROM policy_setting")
            conn.executemany("INSERT INTO policy_setting VALUES (?, ?)", sorted(defaults.items()))
            conn.execute("UPDATE scenario_state SET now_min = ? WHERE id = 1", (scenario.default_now_min,))
        return deleted
    finally:
        conn.close()


__all__ = ["RUNTIME_TABLES", "clock", "reset_runtime_state"]