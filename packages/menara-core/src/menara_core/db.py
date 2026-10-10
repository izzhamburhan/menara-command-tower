"""SQLite access. Every MCP reads the shared file; each writes only the tables it owns.

Ownership is enforced with a SQLite authorizer, so a bug cannot write another MCP's table.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection
from pathlib import Path
from typing import Any

from menara_core.errors import DatabaseNotSeededError

_WRITE_ACTIONS = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}
_DDL_ACTIONS = {
    getattr(sqlite3, name)
    for name in dir(sqlite3)
    if name.startswith(("SQLITE_CREATE_", "SQLITE_DROP_", "SQLITE_ALTER_"))
}
BUSY_TIMEOUT_MS = 5000


def _authorizer(owned: frozenset[str]) -> Any:
    def authorize(action: int, arg1: str | None, *_: Any) -> int:
        if action in _DDL_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action in _WRITE_ACTIONS and arg1 not in owned:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return authorize


def connect(path: Path, owned_tables: Collection[str] = ()) -> sqlite3.Connection:
    """Open the shared DB. No owned tables means a strictly read-only connection."""
    resolved = path.resolve()
    if not resolved.exists():
        raise DatabaseNotSeededError(
            f"Database not found at {resolved}. Run `uv run menara-seed` from the repo root."
        )
    owned = frozenset(owned_tables)
    mode = "rw" if owned else "ro"
    conn = sqlite3.connect(f"{resolved.as_uri()}?mode={mode}", uri=True, timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    if owned:
        conn.set_authorizer(_authorizer(owned))
    return conn
