"""ran-mcp tool logic.

Sandboxed RAN changes. Every change needs a signed policy token that this server verifies locally (it never
calls policy-mcp). It owns ran_change, ran_change_item and ran_kpi_effect; readers of tower KPIs apply the
effect through menara_core.kpi_overlay. It reads the `cell` and `tower` config tables and `ran_script`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from menara_core import clock, network_model, settings
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.ids import (
    enodeb_of_cell,
    parse_cell_id,
    parse_change_id,
    parse_enodeb,
    target_key,
)
from menara_core.tokens import PolicyToken, verify_token

from ran_mcp.models import CellConfig, Change, ChangeItem, ChangeList, RanConfig

SOURCE = "ran-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"ran_change", "ran_change_item", "ran_kpi_effect"})
MAX_ITEMS = 30
MIN_TILT_DEG, MAX_TILT_DEG = 0.0, 15.0
MAX_LIMIT = 500
STATUSES = {"ACTIVE", "REVERTED", "COMPLETED"}


# ---------- lookups ----------


def _tower(conn: sqlite3.Connection, name: str) -> str:
    if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
        raise NotFoundError(f"Tower {name} not found")
    return name


def _cells(conn: sqlite3.Connection, enodeb_name: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM cell WHERE enodeb_name = ? ORDER BY cell_id", (enodeb_name,)).fetchall()


def _applied_delta(conn: sqlite3.Connection, cell_id: str) -> float:
    row = conn.execute(
        "SELECT COALESCE(SUM(i.tilt_delta_deg), 0) FROM ran_change_item i JOIN ran_change c ON c.change_id = i.change_id "
        "WHERE i.cell_id = ? AND c.status = 'ACTIVE'",
        (cell_id,),
    ).fetchone()
    return float(row[0])


def _verify(token: str, action: str, towers: list[str]) -> PolicyToken:
    return verify_token(settings.signing_key(), token, action=action, target=target_key(towers))


def _change(conn: sqlite3.Connection, row: sqlite3.Row) -> Change:
    items = [
        ChangeItem(
            enodeb_name=r["enodeb_name"],
            cell_id=r["cell_id"],
            tilt_delta_deg=r["tilt_delta_deg"],
            attempt=r["attempt"],
        )
        for r in conn.execute(
            "SELECT * FROM ran_change_item WHERE change_id = ? ORDER BY cell_id", (row["change_id"],)
        )
    ]
    return Change(
        change_id=row["change_id"],
        action=row["action"],
        status=row["status"],
        applied_at=row["applied_at"],
        reverted_at=row["reverted_at"],
        approved_by=row["approved_by"],
        reason=row["reason"],
        items=items,
        towers=sorted({i.enodeb_name for i in items}),
    )


def _require_change(conn: sqlite3.Connection, change_id: str) -> sqlite3.Row:
    cid = parse_change_id(change_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM ran_change WHERE change_id = ?", (cid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Change {cid} not found")
    return row


def _new_change(conn: sqlite3.Connection, action: str, approved_by: str, reason: str) -> str:
    stamp = clock.as_of(conn)
    cursor = conn.execute(
        "INSERT INTO ran_change (action, status, applied_min, applied_at, approved_by, reason) "
        "VALUES (?, 'ACTIVE', ?, ?, ?, ?)",
        (action, clock.now_min(conn), stamp, approved_by, reason),
    )
    change_id = f"CHG-{int(cursor.lastrowid or 0):04d}"
    conn.execute("UPDATE ran_change SET change_id = ? WHERE seq = ?", (change_id, cursor.lastrowid))
    return change_id


def _clean_reason(reason: str) -> str:
    return reason.strip()[:300]


# ---------- ran_get_config ----------


def get_config(conn: sqlite3.Connection, enodeb_name: str) -> Envelope[RanConfig]:
    name = _tower(conn, parse_enodeb(enodeb_name))
    cells = []
    for row in _cells(conn, name):
        delta = _applied_delta(conn, row["cell_id"])
        cells.append(
            CellConfig(
                cell_id=row["cell_id"],
                band=row["band"],
                base_tilt_deg=row["tilt_deg"],
                applied_delta_deg=round(delta, 2),
                tilt_deg=round(row["tilt_deg"] + delta, 2),
            )
        )
    active = [
        r["change_id"]
        for r in conn.execute(
            "SELECT DISTINCT c.change_id FROM ran_change c JOIN ran_change_item i ON i.change_id = c.change_id "
            "WHERE c.status = 'ACTIVE' AND i.enodeb_name = ? ORDER BY c.change_id",
            (name,),
        )
    ]
    return wrap(
        conn,
        source=SOURCE,
        tool="ran_get_config",
        data=RanConfig(enodeb_name=name, cells=cells, active_changes=active),
        ref=name,
    )


# ---------- ran_tilt_cells ----------


def _expand(conn: sqlite3.Connection, changes: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    """cell_id -> (enodeb_name, delta). A tower name means every cell on it."""
    if not changes:
        raise InvalidInputError("changes must not be empty")
    expanded: dict[str, tuple[str, float]] = {}
    for item in changes:
        try:
            delta = float(item["tilt_delta_deg"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidInputError("each change needs a numeric tilt_delta_deg") from exc
        if abs(delta) > network_model.MAX_TILT_DELTA_DEG:
            raise InvalidInputError(f"tilt_delta_deg must be within +/-{network_model.MAX_TILT_DELTA_DEG:g}")
        if ("cell_id" in item) == ("enodeb_name" in item):
            raise InvalidInputError("each change needs exactly one of cell_id or enodeb_name")
        if "cell_id" in item:
            cell = parse_cell_id(str(item["cell_id"]))
            tower = _tower(conn, enodeb_of_cell(cell))
            if conn.execute("SELECT 1 FROM cell WHERE cell_id = ?", (cell,)).fetchone() is None:
                raise NotFoundError(f"Cell {cell} not found")
            targets = [(cell, tower)]
        else:
            tower = _tower(conn, parse_enodeb(str(item["enodeb_name"])))
            targets = [(r["cell_id"], tower) for r in _cells(conn, tower)]
        for cell_id, owner in targets:
            if cell_id in expanded:
                raise InvalidInputError(f"cell {cell_id} appears more than once")
            expanded[cell_id] = (owner, delta)
    if len(expanded) > MAX_ITEMS:
        raise InvalidInputError(f"at most {MAX_ITEMS} cells per change")
    return expanded


def tilt_cells(
    conn: sqlite3.Connection, changes: list[dict[str, Any]], policy_token: str, reason: str = ""
) -> Envelope[Change]:
    """Apply tilt changes to cells or whole towers. Needs a token for action ran_tilt_cells on these towers."""
    expanded = _expand(conn, changes)
    towers = sorted({tower for tower, _ in expanded.values()})
    grant = _verify(policy_token, "ran_tilt_cells", towers)

    for cell_id, (_tower_name, delta) in expanded.items():
        row = conn.execute("SELECT tilt_deg FROM cell WHERE cell_id = ?", (cell_id,)).fetchone()
        final = row["tilt_deg"] + _applied_delta(conn, cell_id) + delta
        if not MIN_TILT_DEG <= final <= MAX_TILT_DEG:
            raise InvalidInputError(
                f"cell {cell_id} would end at {final:g} degrees; allowed range is {MIN_TILT_DEG:g} to {MAX_TILT_DEG:g}"
            )

    now = clock.now_min(conn)
    change_id = _new_change(conn, "ran_tilt_cells", grant.approved_by, _clean_reason(reason))
    for tower in towers:
        cells = {c["cell_id"] for c in _cells(conn, tower)}
        attempt = 1 + int(
            conn.execute(
                "SELECT COUNT(DISTINCT i.change_id) FROM ran_change_item i JOIN ran_change c ON c.change_id = i.change_id "
                "WHERE i.enodeb_name = ? AND c.action = 'ran_tilt_cells' AND i.change_id != ?",
                (tower, change_id),
            ).fetchone()[0]
        )
        script = conn.execute(
            "SELECT efficacy FROM ran_script WHERE action = 'ran_tilt_cells' AND enodeb_name = ? AND attempt = ?",
            (tower, attempt),
        ).fetchone()
        efficacy = float(script["efficacy"]) if script else 1.0
        total = 0.0
        for cell_id, (owner, delta) in expanded.items():
            if owner != tower:
                continue
            total += delta
            conn.execute(
                "INSERT INTO ran_change_item VALUES (?, ?, ?, ?, ?, ?)", (change_id, tower, cell_id, delta, efficacy, attempt)
            )
        prb_f, drop_f, thr_f = network_model.effect_factors(total / max(1, len(cells)), efficacy)
        conn.execute("INSERT INTO ran_kpi_effect VALUES (?, ?, ?, ?, ?, ?)", (change_id, tower, now, prb_f, drop_f, thr_f))
    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="ran_tilt_cells",
        data=_change(conn, _require_change(conn, change_id)),
        ref=change_id,
        warnings=["Sandboxed: no real network was changed. Verify the effect with tower KPIs."],
    )


# ---------- ran_reset_cell ----------


def reset_cell(conn: sqlite3.Connection, cell_id: str, policy_token: str, reason: str = "") -> Envelope[Change]:
    """Soft-reset one cell. Needs a token for action ran_reset_cell on its tower."""
    cell = parse_cell_id(cell_id)
    tower = _tower(conn, enodeb_of_cell(cell))
    if conn.execute("SELECT 1 FROM cell WHERE cell_id = ?", (cell,)).fetchone() is None:
        raise NotFoundError(f"Cell {cell} not found")
    grant = _verify(policy_token, "ran_reset_cell", [tower])
    change_id = _new_change(conn, "ran_reset_cell", grant.approved_by, _clean_reason(reason))
    conn.execute("UPDATE ran_change SET status = 'COMPLETED' WHERE change_id = ?", (change_id,))
    conn.execute("INSERT INTO ran_change_item VALUES (?, ?, ?, 0, 1.0, 1)", (change_id, tower, cell))
    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="ran_reset_cell",
        data=_change(conn, _require_change(conn, change_id)),
        ref=change_id,
        warnings=["Sandboxed: no real cell was reset."],
    )


# ---------- ran_revert_change ----------


def revert_change(
    conn: sqlite3.Connection, change_id: str, policy_token: str, reason: str = ""
) -> Envelope[Change]:
    """Roll back an active change. Needs a token for action ran_revert_tilt on the same towers."""
    row = _require_change(conn, change_id)
    if row["status"] != "ACTIVE":
        raise InvalidInputError(f"Change {row['change_id']} is {row['status']}; there is nothing to revert")
    towers = [
        r["enodeb_name"]
        for r in conn.execute(
            "SELECT DISTINCT enodeb_name FROM ran_change_item WHERE change_id = ? ORDER BY enodeb_name",
            (row["change_id"],),
        )
    ]
    _verify(policy_token, "ran_revert_tilt", towers)
    conn.execute(
        "UPDATE ran_change SET status = 'REVERTED', reverted_min = ?, reverted_at = ?, reason = reason || ? "
        "WHERE change_id = ?",
        (clock.now_min(conn), clock.as_of(conn), f" | revert: {_clean_reason(reason)}" if reason.strip() else "", row["change_id"]),
    )
    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="ran_revert_change",
        data=_change(conn, _require_change(conn, row["change_id"])),
        ref=row["change_id"],
    )


# ---------- reads ----------


def get_change(conn: sqlite3.Connection, change_id: str) -> Envelope[Change]:
    row = _require_change(conn, change_id)
    return wrap(conn, source=SOURCE, tool="ran_get_change", data=_change(conn, row), ref=row["change_id"])


def list_changes(
    conn: sqlite3.Connection, status: str | None = None, enodeb_name: str | None = None, limit: int = 50
) -> Envelope[ChangeList]:
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    name = parse_enodeb(enodeb_name) if enodeb_name else None
    rows = conn.execute(
        "SELECT * FROM ran_change c WHERE (? IS NULL OR c.status = ?) AND (? IS NULL OR EXISTS ("
        "SELECT 1 FROM ran_change_item i WHERE i.change_id = c.change_id AND i.enodeb_name = ?)) "
        "ORDER BY c.seq DESC LIMIT ?",
        (status, status, name, name, limit),
    ).fetchall()
    changes = [_change(conn, r) for r in rows]
    return wrap(conn, source=SOURCE, tool="ran_list_changes", data=ChangeList(changes=changes, returned=len(changes)))

