"""field-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Owns `field_job` (work orders that were approved and dispatched). Reads, read-only: `technician`, `spare_part`, `tower`,
`flood_extent`. The crew is fictional; speeds, work times and stock are invented.

Model: a technician drives from their depot at 55 km/h. Where the tower is under floodwater (depth 0.3 m or more, deepest
at the centre of a flood extent) the road is not safe: the crew go by boat, which adds 25 minutes. A job is EN_ROUTE until
its ETA, ON_SITE for 90 minutes of work, then DONE, following the scenario clock. Dispatching commits staff, so it needs a
signed policy token for `workforce_create_order` (policy always asks a human).
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime
from typing import cast

from menara_core import clock, settings
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import haversine_km
from menara_core.ids import parse_enodeb, target_key
from menara_core.tokens import verify_token

from field_mcp.models import Access, Candidate, Crew, Job, JobList, JobStatus, PartStock

SOURCE = "field-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"field_job"})
ACTION = "workforce_create_order"
SKILLS = ("POWER", "RAN", "FIBRE", "CIVIL")
SKILL_PARTS = {"POWER": ("GENERATOR", "RECTIFIER", "BATTERY"), "RAN": ("ANTENNA",), "FIBRE": (), "CIVIL": ()}
ROAD_KMH = 55.0
BOAT_EXTRA_MIN = 25
BOAT_DEPTH_M = 0.3
WORK_MIN = 90
MAX_CANDIDATES = 5
STATUSES = ("EN_ROUTE", "ON_SITE", "DONE")
ACCESS_CHOICES = ("AUTO", "ROAD", "BOAT")
MIN_TASK, MAX_TASK = 3, 200
MAX_LIMIT = 200


def on_shift(hour: int, start: int, end: int) -> bool:
    """Is a local hour inside a shift? A shift may run past midnight (18 to 6)."""
    return start <= hour < end if start < end else hour >= start or hour < end


def _hour(conn: sqlite3.Connection) -> int:
    return datetime.fromisoformat(clock.as_of(conn)).hour


def _tower(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT enodeb_name, lat, lng FROM tower WHERE enodeb_name = ?", (name,)).fetchone()
    if row is None:
        raise NotFoundError(f"Tower {name} not found")
    return row  # type: ignore[no-any-return]


def _depth(conn: sqlite3.Connection, tower: sqlite3.Row, now: int) -> float:
    depth = 0.0
    for e in conn.execute("SELECT lat, lng, radius_km, max_depth_m FROM flood_extent WHERE from_min <= ?", (now,)):
        distance = haversine_km(tower["lat"], tower["lng"], e["lat"], e["lng"])
        if distance < e["radius_km"]:
            depth = max(depth, e["max_depth_m"] * (1 - distance / e["radius_km"]))
    return round(depth, 2)


def _access(depth: float) -> Access:
    return "BOAT" if depth >= BOAT_DEPTH_M else "ROAD"


def _eta(distance_km: float, access: Access) -> int:
    return math.ceil(distance_km / ROAD_KMH * 60) + (BOAT_EXTRA_MIN if access == "BOAT" else 0)


def _busy(conn: sqlite3.Connection, tech_id: str, now: int) -> bool:
    return any(
        r["dispatched_min"] <= now < r["dispatched_min"] + r["eta_min"] + WORK_MIN
        for r in conn.execute("SELECT dispatched_min, eta_min FROM field_job WHERE tech_id = ?", (tech_id,))
    )


def _check_skill(skill: str) -> None:
    if skill not in SKILLS:
        raise InvalidInputError(f"skill must be one of {list(SKILLS)}")


def find_crew(conn: sqlite3.Connection, enodeb_name: str, skill: str) -> Envelope[Crew]:
    """Technicians with a skill who are on shift and free, ranked by ETA, with the access mode, parts and a safety note."""
    _check_skill(skill)
    name = parse_enodeb(enodeb_name)
    tower = _tower(conn, name)
    now, hour = clock.now_min(conn), _hour(conn)
    depth = _depth(conn, tower, now)
    access = _access(depth)
    candidates: list[Candidate] = []
    for t in conn.execute("SELECT * FROM technician ORDER BY tech_id"):
        skills = t["skills"].split(",")
        if skill not in skills or not on_shift(hour, t["shift_start_hour"], t["shift_end_hour"]) or _busy(conn, t["tech_id"], now):
            continue
        distance = haversine_km(t["lat"], t["lng"], tower["lat"], tower["lng"])
        stock = {r["part"]: r["qty"] for r in conn.execute("SELECT part, qty FROM spare_part WHERE depot_id = ?", (t["depot_id"],))}
        candidates.append(
            Candidate(
                tech_id=t["tech_id"], name=t["name"], depot_id=t["depot_id"], skills=skills, distance_km=round(distance, 1),
                eta_min=_eta(distance, access), access=access, parts=[PartStock(part=p, qty=stock.get(p, 0)) for p in SKILL_PARTS[skill]],
            )
        )
    candidates = sorted(candidates, key=lambda c: (c.eta_min, c.tech_id))[:MAX_CANDIDATES]
    note = (
        f"Access to {name} is under about {depth:g} m of floodwater: the road is not safe, so the crew go by boat "
        f"(+{BOAT_EXTRA_MIN} min). Expect fast-flowing water at the entrance."
        if access == "BOAT"
        else ""
    )
    data = Crew(
        enodeb_name=name, skill=skill, access=access, flood_depth_m=depth, road_safe=access == "ROAD", safe_to_dispatch=True,
        safety_note=note, candidates=candidates,
    )
    warnings = [note] if note else []
    if not candidates:
        warnings.append(f"Nobody with the {skill} skill is on shift and free right now.")
    return wrap(conn, source=SOURCE, tool="field_find_crew", data=data, ref=f"{name}:{skill}", warnings=warnings)


def _status(row: sqlite3.Row, now: int) -> tuple[JobStatus, int]:
    elapsed = now - row["dispatched_min"]
    if elapsed < row["eta_min"]:
        return "EN_ROUTE", row["eta_min"] - elapsed
    if elapsed < row["eta_min"] + WORK_MIN:
        return "ON_SITE", 0
    return "DONE", 0


def _job(conn: sqlite3.Connection, row: sqlite3.Row, now: int) -> Job:
    status, left = _status(row, now)
    tech = conn.execute("SELECT name FROM technician WHERE tech_id = ?", (row["tech_id"],)).fetchone()
    return Job(
        job_id=row["job_id"], tech_id=row["tech_id"], tech_name=tech["name"] if tech else row["tech_id"], enodeb_name=row["enodeb_name"],
        task=row["task"], skill=row["skill"], dispatched_at=row["dispatched_at"], eta_min=row["eta_min"], access=cast(Access, row["access"]),
        approved_by=row["approved_by"], status=status, eta_left_min=left,
    )


def dispatch(
    conn: sqlite3.Connection,
    enodeb_name: str,
    tech_id: str,
    task: str,
    policy_token: str,
    reason: str = "",
    skill: str = "POWER",
    access: str = "AUTO",
) -> Envelope[Job]:
    """Send a technician to a tower. Needs a policy token for action workforce_create_order on that tower."""
    text = task.strip()
    if not MIN_TASK <= len(text) <= MAX_TASK:
        raise InvalidInputError(f"task must be {MIN_TASK} to {MAX_TASK} characters")
    _check_skill(skill)
    if access not in ACCESS_CHOICES:
        raise InvalidInputError(f"access must be one of {list(ACCESS_CHOICES)}")
    name = parse_enodeb(enodeb_name)
    tower = _tower(conn, name)
    tech = conn.execute("SELECT * FROM technician WHERE tech_id = ?", (tech_id,)).fetchone()
    if tech is None:
        raise NotFoundError(f"Technician {tech_id} not found")
    grant = verify_token(settings.signing_key(), policy_token, action=ACTION, target=target_key([name]))
    now = clock.now_min(conn)
    if not on_shift(_hour(conn), tech["shift_start_hour"], tech["shift_end_hour"]):
        raise InvalidInputError(f"{tech_id} is not on shift now")
    if skill not in tech["skills"].split(","):
        raise InvalidInputError(f"{tech_id} does not have the {skill} skill")
    if _busy(conn, tech_id, now):
        raise InvalidInputError(f"{tech_id} is already on a job")
    depth = _depth(conn, tower, now)
    chosen = cast(Access, _access(depth) if access == "AUTO" else access)
    if chosen == "ROAD" and depth >= BOAT_DEPTH_M:
        raise InvalidInputError(f"{name} is under about {depth:g} m of floodwater: the road is not safe, send the crew by boat")
    eta = _eta(haversine_km(tech["lat"], tech["lng"], tower["lat"], tower["lng"]), chosen)
    cursor = conn.execute(
        "INSERT INTO field_job (tech_id, enodeb_name, task, skill, dispatched_min, dispatched_at, eta_min, access, approved_by, reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (tech_id, name, text, skill, now, clock.as_of(conn), eta, chosen, grant.approved_by, reason.strip()[:300]),
    )
    job_id = f"JOB-{int(cursor.lastrowid or 0):04d}"
    conn.execute("UPDATE field_job SET job_id = ? WHERE seq = ?", (job_id, cursor.lastrowid))
    conn.commit()
    row = conn.execute("SELECT * FROM field_job WHERE seq = ?", (cursor.lastrowid,)).fetchone()
    return wrap(conn, source=SOURCE, tool="field_dispatch", data=_job(conn, row, now), ref=job_id)


def list_jobs(conn: sqlite3.Connection, status: str | None = None, limit: int = 50) -> Envelope[JobList]:
    """Work orders so far, newest first, with a status that follows the scenario clock."""
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {list(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    now = clock.now_min(conn)
    jobs = [_job(conn, r, now) for r in conn.execute("SELECT * FROM field_job WHERE dispatched_min <= ? ORDER BY seq DESC", (now,))]
    if status is not None:
        jobs = [j for j in jobs if j.status == status]
    jobs = jobs[:limit]
    return wrap(conn, source=SOURCE, tool="field_list_jobs", data=JobList(jobs=jobs, returned=len(jobs)))
