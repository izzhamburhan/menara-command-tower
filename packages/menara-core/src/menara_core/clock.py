"""Scripted scenario clock. t_min is minutes since scenario T0 (negative = before)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from menara_core.errors import DatabaseNotSeededError


def _meta(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM seed_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise DatabaseNotSeededError(f"seed_meta is missing {key!r}; re-run `uv run menara-seed`.")
    return str(row["value"])


def now_min(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT now_min FROM scenario_state WHERE id = 1").fetchone()
    if row is None:
        raise DatabaseNotSeededError("scenario_state is empty; re-run `uv run menara-seed`.")
    return int(row["now_min"])


def iso_at(conn: sqlite3.Connection, t_min: int) -> str:
    start = datetime.fromisoformat(_meta(conn, "scenario_start"))
    return (start + timedelta(minutes=t_min)).isoformat()


def as_of(conn: sqlite3.Connection) -> str:
    return iso_at(conn, now_min(conn))


def set_now(conn: sqlite3.Connection, minutes: int) -> None:
    """Caller must hold a connection that owns scenario_state."""
    conn.execute("UPDATE scenario_state SET now_min = ? WHERE id = 1", (minutes,))
    conn.commit()
