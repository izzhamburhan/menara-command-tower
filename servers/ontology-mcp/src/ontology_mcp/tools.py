"""ontology-mcp tool logic.

Links towers to their neighbours, feeders, flood gauges, critical sites and subscribers, and owns the
Incident object the agent creates. It may read other domains' base tables (read-only); it writes only
`incident` and `incident_ticket`.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from typing import Any, cast

from menara_core import clock, kpi_overlay
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km
from menara_core.ids import SITE_RE, parse_enodeb, parse_incident_id, parse_ticket_id
from pydantic import ValidationError

from ontology_mcp.models import (
    BlastRadius,
    Dependency,
    EvidenceRef,
    FeederRef,
    Incident,
    IncidentList,
    IncidentNote,
    NeighbourRef,
    Neighbours,
    SiteRef,
    TowerRef,
    TowerStatus,
    Upstream,
)

SOURCE = "ontology-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"incident", "incident_ticket"})
DEFAULT_RADIUS_KM = 20.0
GAUGE_SEARCH_KM = 30.0
MAX_LIMIT = 1000
CAUSES = {"FLOOD", "POWER", "TRANSPORT", "HARDWARE", "CONFIG", "UNKNOWN"}
STATUSES = {"OPEN", "MITIGATING", "RESOLVED"}
TRANSITIONS: dict[str, set[str]] = {"OPEN": {"MITIGATING", "RESOLVED"}, "MITIGATING": {"RESOLVED"}, "RESOLVED": set()}
MAX_TICKETS, MAX_EVIDENCE, MAX_NOTE_CHARS = 200, 30, 500
SUMMARY_MIN, SUMMARY_MAX = 5, 500


# ---------- shared lookups ----------


def _resolve_tower(conn: sqlite3.Connection, value: str) -> sqlite3.Row:
    """Accept an enodeb_name (KKRI-0142) or its site_id (SITE-KKRI-0142)."""
    text = value.strip()
    name = text[len("SITE-") :] if SITE_RE.match(text) else parse_enodeb(text)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM tower WHERE enodeb_name = ?", (name,)).fetchone()
    if row is None:
        raise NotFoundError(f"Tower {name} not found")
    return row


def _status(conn: sqlite3.Connection, name: str, now: int) -> TowerStatus:
    row = conn.execute(
        "SELECT status FROM tower_state WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (name, now),
    ).fetchone()
    return cast(TowerStatus, row["status"]) if row else "UNKNOWN"


def _subscribers(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT subscribers_est FROM tower_subscribers WHERE enodeb_name = ?", (name,)).fetchone()
    return int(row["subscribers_est"]) if row else 0


def _tower_ref(conn: sqlite3.Connection, row: sqlite3.Row, distance_km: float, now: int) -> TowerRef:
    return TowerRef(
        enodeb_name=row["enodeb_name"],
        site_id=row["site_id"],
        town=row["town"],
        state=row["state"],
        lat=row["lat"],
        lng=row["lng"],
        status=_status(conn, row["enodeb_name"], now),
        distance_km=round(distance_km, 2),
        subscribers_est=_subscribers(conn, row["enodeb_name"]),
    )


def _feeder_status(conn: sqlite3.Connection, feeder_id: str, now: int) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM grid_feeder_state WHERE feeder_id = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (feeder_id, now),
    ).fetchone()
    return row


# ---------- ontology_blast_radius ----------


def blast_radius(
    conn: sqlite3.Connection, site: str, radius_km: float = DEFAULT_RADIUS_KM, limit: int = 200
) -> Envelope[BlastRadius]:
    """Everything within radius_km of a tower that shares its fate if the area is hit."""
    origin = _resolve_tower(conn, site)
    if not 1 <= radius_km <= 100:
        raise InvalidInputError("radius_km must be between 1 and 100")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    now = clock.now_min(conn)
    min_lat, min_lng, max_lat, max_lng = bbox_around(origin["lat"], origin["lng"], radius_km)
    candidates = conn.execute(
        "SELECT * FROM tower WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (min_lat, max_lat, min_lng, max_lng),
    ).fetchall()
    inside = sorted(
        (haversine_km(origin["lat"], origin["lng"], r["lat"], r["lng"]), r["enodeb_name"], r)
        for r in candidates
        if r["enodeb_name"] != origin["enodeb_name"]
    )
    inside = [t for t in inside if t[0] <= radius_km]
    refs = [_tower_ref(conn, row, dist, now) for dist, _, row in inside]
    origin_ref = _tower_ref(conn, origin, 0.0, now)
    names = {origin["enodeb_name"], *(r.enodeb_name for r in refs)}

    sites = _sites_served_by(conn, names, now)
    feeder_counts: Counter[str] = Counter()
    for name in names:
        link = conn.execute("SELECT feeder_id FROM grid_feeder_tower WHERE enodeb_name = ?", (name,)).fetchone()
        if link:
            feeder_counts[link["feeder_id"]] += 1
    feeders: list[FeederRef] = []
    for feeder_id, count in sorted(feeder_counts.items()):
        meta = conn.execute("SELECT name FROM grid_feeder WHERE feeder_id = ?", (feeder_id,)).fetchone()
        state = _feeder_status(conn, feeder_id, now)
        feeders.append(
            FeederRef(
                feeder_id=feeder_id,
                name=meta["name"] if meta else feeder_id,
                status=state["status"] if state else "ENERGISED",
                towers_in_radius=count,
            )
        )
    order = {"TRIPPED": 0, "AT_RISK": 1, "ENERGISED": 2}
    feeders.sort(key=lambda f: (order.get(f.status, 3), f.feeder_id))

    total_at_risk = sum(r.subscribers_est for r in refs)
    data = BlastRadius(
        origin=origin_ref,
        radius_km=radius_km,
        at_risk_towers=refs[:limit],
        towers_at_risk=len(refs),
        subscribers_in_radius=origin_ref.subscribers_est + total_at_risk,
        subscribers_at_risk=total_at_risk,
        critical_sites=sites[:limit],
        counts_by_kind=dict(Counter(s.kind for s in sites)),
        emergency_sites=sum(s.emergency_service for s in sites),
        sla_customers=sum(s.sla_customer for s in sites),
        feeders=feeders,
        truncated=len(refs) > limit or len(sites) > limit,
    )
    warnings = [f"Lists truncated at {limit}; totals and counts cover everything in range"] if data.truncated else []
    return wrap(
        conn,
        source=SOURCE,
        tool="ontology_blast_radius",
        data=data,
        ref=origin["enodeb_name"],
        warnings=warnings,
    )


def _sites_served_by(conn: sqlite3.Connection, names: set[str], now: int) -> list[SiteRef]:
    rows = conn.execute("SELECT * FROM critical_site ORDER BY priority, critical_site_id").fetchall()
    return [
        SiteRef(
            critical_site_id=r["critical_site_id"],
            name=r["name"],
            kind=r["kind"],
            priority=r["priority"],
            emergency_service=bool(r["emergency_service"]),
            sla_customer=r["kind"] == "ENTERPRISE",
            serving_enodeb=r["serving_enodeb"],
            serving_status=_status(conn, r["serving_enodeb"], now),
        )
        for r in rows
        if r["serving_enodeb"] in names
    ]


# ---------- ontology_neighbours ----------


def neighbours(conn: sqlite3.Connection, site: str) -> Envelope[Neighbours]:
    origin = _resolve_tower(conn, site)
    name, now = origin["enodeb_name"], clock.now_min(conn)
    found: dict[str, dict[str, Any]] = {}
    for r in conn.execute("SELECT neighbour_name, distance_km FROM tower_neighbour WHERE enodeb_name = ?", (name,)):
        found.setdefault(r["neighbour_name"], {"distance": r["distance_km"], "nearest": False, "lists": False})[
            "nearest"
        ] = True
    for r in conn.execute("SELECT enodeb_name, distance_km FROM tower_neighbour WHERE neighbour_name = ?", (name,)):
        found.setdefault(r["enodeb_name"], {"distance": r["distance_km"], "nearest": False, "lists": False})[
            "lists"
        ] = True
    refs: list[NeighbourRef] = []
    for other, info in found.items():
        kpi = conn.execute(
            "SELECT t_min, prb_util, drop_rate, throughput_mbps FROM tower_kpi "
            "WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
            (other, now),
        ).fetchone()
        refs.append(
            NeighbourRef(
                enodeb_name=other,
                distance_km=info["distance"],
                status=_status(conn, other, now),
                prb_util=kpi_overlay.adjust(
                    conn, other, kpi["t_min"], kpi["prb_util"], kpi["drop_rate"], kpi["throughput_mbps"]
                )[0]
                if kpi
                else None,
                nearest_of_origin=info["nearest"],
                lists_origin=info["lists"],
            )
        )
    refs.sort(key=lambda n: (n.distance_km, n.enodeb_name))
    return wrap(
        conn,
        source=SOURCE,
        tool="ontology_neighbours",
        data=Neighbours(enodeb_name=name, neighbours=refs),
        ref=name,
    )


# ---------- ontology_upstream_of ----------


def upstream_of(conn: sqlite3.Connection, site: str) -> Envelope[Upstream]:
    """What the tower depends on: its power feeder and the nearest river gauge."""
    origin = _resolve_tower(conn, site)
    name, now = origin["enodeb_name"], clock.now_min(conn)
    deps: list[Dependency] = []
    shared: list[str] = []
    link = conn.execute("SELECT feeder_id FROM grid_feeder_tower WHERE enodeb_name = ?", (name,)).fetchone()
    if link:
        feeder = conn.execute("SELECT * FROM grid_feeder WHERE feeder_id = ?", (link["feeder_id"],)).fetchone()
        state = _feeder_status(conn, link["feeder_id"], now)
        shared = [
            r["enodeb_name"]
            for r in conn.execute(
                "SELECT enodeb_name FROM grid_feeder_tower WHERE feeder_id = ? AND enodeb_name != ? ORDER BY enodeb_name",
                (link["feeder_id"], name),
            )
        ]
        deps.append(
            Dependency(
                kind="POWER_FEEDER",
                id=link["feeder_id"],
                name=feeder["name"],
                status=state["status"] if state else "ENERGISED",
                detail=(state["note"] if state else "Normal supply") + f"; {feeder['customers']} customers",
            )
        )
    gauge = _nearest_gauge(conn, origin["lat"], origin["lng"])
    if gauge is not None:
        level = conn.execute(
            "SELECT level_m FROM flood_reading WHERE gauge_id = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
            (gauge["gauge_id"], now),
        ).fetchone()
        reading = float(level["level_m"]) if level else None
        status = "NORMAL"
        if reading is not None and reading >= gauge["danger_m"]:
            status = "DANGER"
        elif reading is not None and reading >= gauge["warning_m"]:
            status = "WARNING"
        deps.append(
            Dependency(
                kind="FLOOD_GAUGE",
                id=gauge["gauge_id"],
                name=gauge["river"],
                status=status,
                detail=f"level {reading} m against danger {gauge['danger_m']} m",
            )
        )
    return wrap(
        conn,
        source=SOURCE,
        tool="ontology_upstream_of",
        data=Upstream(enodeb_name=name, dependencies=deps, shares_feeder_with=shared),
        ref=name,
    )


def _nearest_gauge(conn: sqlite3.Connection, lat: float, lng: float) -> sqlite3.Row | None:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, GAUGE_SEARCH_KM)
    rows = conn.execute(
        "SELECT * FROM flood_gauge WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (min_lat, max_lat, min_lng, max_lng),
    ).fetchall()
    scored = sorted((haversine_km(lat, lng, r["lat"], r["lng"]), r["gauge_id"], r) for r in rows)
    return scored[0][2] if scored and scored[0][0] <= GAUGE_SEARCH_KM else None


# ---------- incidents ----------


def _incident(conn: sqlite3.Connection, row: sqlite3.Row) -> Incident:
    tickets = [
        r["ticket_id"]
        for r in conn.execute(
            "SELECT ticket_id FROM incident_ticket WHERE incident_id = ? ORDER BY ticket_id", (row["incident_id"],)
        )
    ]
    return Incident(
        incident_id=row["incident_id"],
        enodeb_name=row["enodeb_name"],
        cause=row["cause"],
        cause_confidence=row["cause_confidence"],
        summary=row["summary"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        ticket_ids=tickets,
        evidence=[EvidenceRef.model_validate(e) for e in json.loads(row["evidence"])],
        notes=[IncidentNote.model_validate(n) for n in json.loads(row["notes"])],
    )


def _require_incident(conn: sqlite3.Connection, incident_id: str) -> sqlite3.Row:
    iid = parse_incident_id(incident_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM incident WHERE incident_id = ?", (iid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Incident {iid} not found")
    return row


def create_incident(
    conn: sqlite3.Connection,
    enodeb_name: str,
    cause: str,
    cause_confidence: float,
    summary: str,
    ticket_ids: list[str] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> Envelope[Incident]:
    """Create the Incident that clusters tickets, points at a tower, names a cause, and cites its evidence."""
    tower = _resolve_tower(conn, enodeb_name)
    if cause not in CAUSES:
        raise InvalidInputError(f"cause must be one of {sorted(CAUSES)}")
    if not 0.0 <= cause_confidence <= 1.0:
        raise InvalidInputError("cause_confidence must be between 0 and 1")
    text = summary.strip()
    if not SUMMARY_MIN <= len(text) <= SUMMARY_MAX:
        raise InvalidInputError(f"summary must be {SUMMARY_MIN}-{SUMMARY_MAX} characters")
    ids = list(dict.fromkeys(parse_ticket_id(t) for t in (ticket_ids or [])))
    if len(ids) > MAX_TICKETS:
        raise InvalidInputError(f"at most {MAX_TICKETS} tickets per incident")
    now = clock.now_min(conn)
    for tid in ids:
        found = conn.execute("SELECT 1 FROM ticket WHERE ticket_id = ? AND created_min <= ?", (tid, now)).fetchone()
        if found is None:
            raise NotFoundError(f"Ticket {tid} not found at the current scenario time")
    refs = evidence or []
    if len(refs) > MAX_EVIDENCE:
        raise InvalidInputError(f"at most {MAX_EVIDENCE} evidence entries per incident")
    try:
        parsed = [EvidenceRef.model_validate(e) for e in refs]
    except ValidationError as exc:
        raise InvalidInputError(f"Invalid evidence entry: {exc.errors()[0]['msg']}") from exc

    existing = conn.execute(
        "SELECT incident_id FROM incident WHERE enodeb_name = ? AND status != 'RESOLVED'", (tower["enodeb_name"],)
    ).fetchone()
    if existing:
        raise InvalidInputError(
            f"Incident {existing['incident_id']} is already open for {tower['enodeb_name']}; update it instead"
        )

    stamp = clock.as_of(conn)
    try:
        cursor = conn.execute(
            "INSERT INTO incident (enodeb_name, cause, cause_confidence, summary, status, created_at, updated_at, evidence) "
            "VALUES (?, ?, ?, ?, 'OPEN', ?, ?, ?)",
            (
                tower["enodeb_name"],
                cause,
                cause_confidence,
                text,
                stamp,
                stamp,
                json.dumps([e.model_dump() for e in parsed], sort_keys=True),
            ),
        )
        incident_id = f"INC-{int(cursor.lastrowid or 0):04d}"
        conn.execute("UPDATE incident SET incident_id = ? WHERE seq = ?", (incident_id, cursor.lastrowid))
        conn.executemany("INSERT INTO incident_ticket VALUES (?, ?)", [(incident_id, t) for t in ids])
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise
    return wrap(
        conn,
        source=SOURCE,
        tool="ontology_create_incident",
        data=_incident(conn, _require_incident(conn, incident_id)),
        ref=incident_id,
    )


def get_incident(conn: sqlite3.Connection, incident_id: str) -> Envelope[Incident]:
    row = _require_incident(conn, incident_id)
    return wrap(
        conn, source=SOURCE, tool="ontology_get_incident", data=_incident(conn, row), ref=row["incident_id"]
    )


def list_incidents(
    conn: sqlite3.Connection, status: str | None = None, enodeb_name: str | None = None, limit: int = 50
) -> Envelope[IncidentList]:
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    name = parse_enodeb(enodeb_name) if enodeb_name else None
    rows = conn.execute(
        "SELECT * FROM incident WHERE (? IS NULL OR status = ?) AND (? IS NULL OR enodeb_name = ?) "
        "ORDER BY seq DESC LIMIT ?",
        (status, status, name, name, limit),
    ).fetchall()
    incidents = [_incident(conn, r) for r in rows]
    return wrap(
        conn,
        source=SOURCE,
        tool="ontology_list_incidents",
        data=IncidentList(incidents=incidents, returned=len(incidents)),
    )


def update_incident(
    conn: sqlite3.Connection, incident_id: str, status: str, note: str | None = None
) -> Envelope[Incident]:
    """Move an incident forward (OPEN, MITIGATING, RESOLVED) and optionally append a note."""
    row = _require_incident(conn, incident_id)
    if status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if status not in TRANSITIONS[row["status"]]:
        allowed = ", ".join(sorted(TRANSITIONS[row["status"]])) or f"none (already {row['status']})"
        raise InvalidInputError(f"Cannot move incident from {row['status']} to {status} (allowed: {allowed})")
    notes: list[dict[str, str]] = json.loads(row["notes"])
    stamp = clock.as_of(conn)
    if note is not None:
        body = note.strip()
        if not body or len(body) > MAX_NOTE_CHARS:
            raise InvalidInputError(f"note must be 1-{MAX_NOTE_CHARS} characters")
        notes.append({"at": stamp, "text": body})
    conn.execute(
        "UPDATE incident SET status = ?, updated_at = ?, notes = ? WHERE incident_id = ?",
        (status, stamp, json.dumps(notes), row["incident_id"]),
    )
    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="ontology_update_incident",
        data=_incident(conn, _require_incident(conn, row["incident_id"])),
        ref=row["incident_id"],
    )

