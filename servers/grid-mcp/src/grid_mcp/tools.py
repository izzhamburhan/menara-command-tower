"""grid-mcp tool logic. Read-only. Power feeders, their state over time, and which towers they supply."""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import NotFoundError
from menara_core.ids import parse_enodeb, parse_feeder_id

from grid_mcp.models import Feeder, FeederDetail, FeederStatus, OutageList, TowerPower

SOURCE = "grid-mcp"
OWNED_TABLES: frozenset[str] = frozenset()

_LATEST_STATE = (
    "SELECT * FROM grid_feeder_state s WHERE s.feeder_id = ? AND s.t_min <= ? ORDER BY s.t_min DESC LIMIT 1"
)
_STATUS_ORDER = {"TRIPPED": 0, "AT_RISK": 1, "ENERGISED": 2}


def _feeder(conn: sqlite3.Connection, feeder: sqlite3.Row, now: int) -> Feeder:
    state: sqlite3.Row | None = conn.execute(_LATEST_STATE, (feeder["feeder_id"], now)).fetchone()
    status: FeederStatus = state["status"] if state else "ENERGISED"
    energised = status == "ENERGISED"
    eta = state["restoration_eta_min"] if state else None
    return Feeder(
        feeder_id=feeder["feeder_id"],
        name=feeder["name"],
        state=feeder["state"],
        status=status,
        since=None if energised or state is None else clock.iso_at(conn, state["t_min"]),
        note=state["note"] if state else "Normal supply",
        restoration_eta=clock.iso_at(conn, eta) if eta is not None else None,
        customers=feeder["customers"],
        customers_affected=feeder["customers"] if status == "TRIPPED" else 0,
    )


def _require_feeder(conn: sqlite3.Connection, feeder_id: str) -> sqlite3.Row:
    fid = parse_feeder_id(feeder_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM grid_feeder WHERE feeder_id = ?", (fid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Feeder {fid} not found")
    return row


def get_tower_power(conn: sqlite3.Connection, enodeb_name: str) -> Envelope[TowerPower]:
    name = parse_enodeb(enodeb_name)
    link: sqlite3.Row | None = conn.execute(
        "SELECT feeder_id FROM grid_feeder_tower WHERE enodeb_name = ?", (name,)
    ).fetchone()
    if link is None:
        raise NotFoundError(f"No power feeder mapped to tower {name}")
    feeder = _feeder(conn, _require_feeder(conn, link["feeder_id"]), clock.now_min(conn))
    data = TowerPower(enodeb_name=name, feeder=feeder, mains_expected=feeder.status != "TRIPPED")
    return wrap(conn, source=SOURCE, tool="grid_get_tower_power", data=data, ref=name)


def get_feeder_status(conn: sqlite3.Connection, feeder_id: str) -> Envelope[FeederDetail]:
    row = _require_feeder(conn, feeder_id)
    towers = [
        r["enodeb_name"]
        for r in conn.execute(
            "SELECT enodeb_name FROM grid_feeder_tower WHERE feeder_id = ? ORDER BY enodeb_name", (row["feeder_id"],)
        )
    ]
    data = FeederDetail(feeder=_feeder(conn, row, clock.now_min(conn)), towers=towers)
    return wrap(conn, source=SOURCE, tool="grid_get_feeder_status", data=data, ref=row["feeder_id"])


def list_outages(conn: sqlite3.Connection, include_at_risk: bool = True) -> Envelope[OutageList]:
    """Feeders that are tripped, and optionally those at risk, as of the scenario clock."""
    now = clock.now_min(conn)
    feeders = [_feeder(conn, row, now) for row in conn.execute("SELECT * FROM grid_feeder ORDER BY feeder_id")]
    wanted = {"TRIPPED", "AT_RISK"} if include_at_risk else {"TRIPPED"}
    hits = sorted(
        (f for f in feeders if f.status in wanted), key=lambda f: (_STATUS_ORDER[f.status], f.feeder_id)
    )
    data = OutageList(feeders=hits, returned=len(hits), customers_affected=sum(f.customers_affected for f in hits))
    return wrap(conn, source=SOURCE, tool="grid_list_outages", data=data)
