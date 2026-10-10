"""drone-mcp tool logic.

Simulated drones. A dispatch needs a signed policy token (verified locally). Flight and inspection follow the
scenario clock: advance it to see the drone arrive, then the canned vision findings appear. It owns
drone_mission and reads `drone`, `drone_finding`, `tower` and `seed_meta`.
"""

from __future__ import annotations

import json
import math
import sqlite3

from menara_core import clock, settings
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import haversine_km
from menara_core.ids import parse_enodeb, parse_mission_id
from menara_core.tokens import verify_token

from drone_mcp.models import (
    DroneInfo,
    DroneList,
    Findings,
    Mission,
    MissionList,
    MissionStatus,
)

SOURCE = "drone-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"drone_mission"})
MAX_RANGE_KM = 150.0
MAX_LIMIT = 500
STATUSES = {"EN_ROUTE", "ON_SITE", "COMPLETE"}


def _meta(conn: sqlite3.Connection, key: str) -> float:
    row = conn.execute("SELECT value FROM seed_meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise NotFoundError(f"seed_meta is missing {key}; re-run `uv run menara-seed`")
    return float(row["value"])


def _tower(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row: sqlite3.Row | None = conn.execute("SELECT * FROM tower WHERE enodeb_name = ?", (name,)).fetchone()
    if row is None:
        raise NotFoundError(f"Tower {name} not found")
    return row


def _busy_until(row: sqlite3.Row) -> int:
    """The drone is out until it has flown there, inspected, and flown back."""
    return int(row["dispatched_min"] + 2 * row["eta_min"] + row["inspect_min"])


def _drone_missions(conn: sqlite3.Connection, drone_id: str, now: int) -> sqlite3.Row | None:
    for row in conn.execute(
        "SELECT * FROM drone_mission WHERE drone_id = ? AND dispatched_min <= ? ORDER BY dispatched_min DESC",
        (drone_id, now),
    ):
        if _busy_until(row) > now:
            return row  # type: ignore[no-any-return]
    return None


def _mission_status(row: sqlite3.Row, now: int) -> tuple[MissionStatus, int]:
    arrive = row["dispatched_min"] + row["eta_min"]
    done = arrive + row["inspect_min"]
    if now < arrive:
        return "EN_ROUTE", max(0, min(99, int((now - row["dispatched_min"]) * 100 / max(1, row["eta_min"]))))
    if now < done:
        return "ON_SITE", 100
    return "COMPLETE", 100


def _iso(conn: sqlite3.Connection, t_min: int) -> str:
    return clock.iso_at(conn, t_min)


def _mission(conn: sqlite3.Connection, row: sqlite3.Row, now: int) -> Mission:
    status, progress = _mission_status(row, now)
    drone = conn.execute("SELECT depot_name FROM drone WHERE drone_id = ?", (row["drone_id"],)).fetchone()
    findings: Findings | None = None
    if status == "COMPLETE":
        stored = conn.execute("SELECT finding FROM drone_finding WHERE enodeb_name = ?", (row["enodeb_name"],)).fetchone()
        if stored is not None:
            findings = Findings.model_validate(json.loads(stored["finding"]))
    arrive = row["dispatched_min"] + row["eta_min"]
    return Mission(
        mission_id=row["mission_id"],
        drone_id=row["drone_id"],
        depot_name=drone["depot_name"] if drone else "",
        enodeb_name=row["enodeb_name"],
        status=status,
        progress_pct=progress,
        distance_km=row["distance_km"],
        dispatched_at=row["dispatched_at"],
        arrives_at=_iso(conn, arrive),
        completes_at=_iso(conn, arrive + row["inspect_min"]),
        approved_by=row["approved_by"],
        reason=row["reason"],
        findings=findings,
    )


def _require_mission(conn: sqlite3.Connection, mission_id: str) -> sqlite3.Row:
    mid = parse_mission_id(mission_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM drone_mission WHERE mission_id = ?", (mid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Mission {mid} not found")
    return row


# ---------- drone_list_drones ----------


def list_drones(conn: sqlite3.Connection) -> Envelope[DroneList]:
    now = clock.now_min(conn)
    drones: list[DroneInfo] = []
    for d in conn.execute("SELECT * FROM drone ORDER BY drone_id").fetchall():
        busy = _drone_missions(conn, d["drone_id"], now)
        drones.append(
            DroneInfo(
                drone_id=d["drone_id"],
                depot_id=d["depot_id"],
                depot_name=d["depot_name"],
                status="ON_MISSION" if busy else "IDLE",
                mission_id=busy["mission_id"] if busy else None,
                available_at=_iso(conn, _busy_until(busy)) if busy else None,
            )
        )
    data = DroneList(drones=drones, idle=sum(d.status == "IDLE" for d in drones), returned=len(drones))
    return wrap(conn, source=SOURCE, tool="drone_list_drones", data=data)


# ---------- drone_dispatch ----------


def dispatch(
    conn: sqlite3.Connection, enodeb_name: str, policy_token: str, reason: str = ""
) -> Envelope[Mission]:
    """Send the nearest idle drone to inspect a tower. Needs a token for action drone_dispatch on that tower."""
    name = parse_enodeb(enodeb_name)
    tower = _tower(conn, name)
    grant = verify_token(settings.signing_key(), policy_token, action="drone_dispatch", target=name)
    now = clock.now_min(conn)

    for active in conn.execute("SELECT * FROM drone_mission WHERE enodeb_name = ?", (name,)):
        if active["dispatched_min"] <= now and _mission_status(active, now)[0] != "COMPLETE":
            raise InvalidInputError(f"Mission {active['mission_id']} is already active for {name}")

    candidates = sorted(
        (haversine_km(d["lat"], d["lng"], tower["lat"], tower["lng"]), d["drone_id"], d)
        for d in conn.execute("SELECT * FROM drone").fetchall()
        if _drone_missions(conn, d["drone_id"], now) is None
    )
    if not candidates or candidates[0][0] > MAX_RANGE_KM:
        raise InvalidInputError(f"No idle drone within {MAX_RANGE_KM:g} km of {name}")
    distance, drone_id, _ = candidates[0]

    speed, inspect = _meta(conn, "drone_speed_kmh"), int(_meta(conn, "drone_inspect_min"))
    eta = math.ceil(distance / speed * 60)
    cursor = conn.execute(
        "INSERT INTO drone_mission (drone_id, enodeb_name, dispatched_min, dispatched_at, distance_km, eta_min, "
        "inspect_min, approved_by, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (drone_id, name, now, clock.as_of(conn), round(distance, 1), eta, inspect, grant.approved_by, reason.strip()[:300]),
    )
    mission_id = f"MIS-{int(cursor.lastrowid or 0):04d}"
    conn.execute("UPDATE drone_mission SET mission_id = ? WHERE seq = ?", (mission_id, cursor.lastrowid))
    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="drone_dispatch",
        data=_mission(conn, _require_mission(conn, mission_id), now),
        ref=mission_id,
        warnings=["Simulated flight: advance the scenario clock to see the drone arrive and the findings appear."],
    )


# ---------- reads ----------


def get_mission(conn: sqlite3.Connection, mission_id: str) -> Envelope[Mission]:
    row = _require_mission(conn, mission_id)
    now = clock.now_min(conn)
    if row["dispatched_min"] > now:
        raise NotFoundError(f"Mission {row['mission_id']} not found at the current scenario time")
    data = _mission(conn, row, now)
    warnings = [] if data.findings else ["Findings appear when the drone has finished its inspection"]
    return wrap(conn, source=SOURCE, tool="drone_get_mission", data=data, ref=row["mission_id"], warnings=warnings)


def list_missions(
    conn: sqlite3.Connection, status: str | None = None, enodeb_name: str | None = None, limit: int = 50
) -> Envelope[MissionList]:
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    name = parse_enodeb(enodeb_name) if enodeb_name else None
    now = clock.now_min(conn)
    rows = conn.execute(
        "SELECT * FROM drone_mission WHERE dispatched_min <= ? AND (? IS NULL OR enodeb_name = ?) ORDER BY seq DESC",
        (now, name, name),
    ).fetchall()
    missions = [_mission(conn, r, now) for r in rows]
    if status:
        missions = [m for m in missions if m.status == status]
    shown = missions[:limit]
    return wrap(conn, source=SOURCE, tool="drone_list_missions", data=MissionList(missions=shown, returned=len(shown)))
