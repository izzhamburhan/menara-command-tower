"""Audit writer. The audit_log table is owned by policy-mcp; only its connection may append."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from menara_core import clock

AUDIT_TABLE = "audit_log"


def append_audit(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    target: str,
    decision: str,
    detail: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO audit_log (at, actor, action, target, decision, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (
            clock.as_of(conn),
            actor,
            action,
            target,
            decision,
            json.dumps(detail or {}, sort_keys=True),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)
