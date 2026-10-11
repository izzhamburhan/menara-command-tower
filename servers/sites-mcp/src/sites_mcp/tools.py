"""sites-mcp tool logic. Read-only. Critical sites and the tower that serves each one."""

from __future__ import annotations

import sqlite3
from collections import Counter

from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.ids import parse_critical_site_id, parse_enodeb

from sites_mcp.models import Site, SiteList, TowerSites

SOURCE = "sites-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
KINDS = {"HOSPITAL", "CLINIC", "POLICE", "FIRE", "SCHOOL", "ENTERPRISE"}
KINDS = {"HOSPITAL", "CLINIC", "POLICE", "FIRE", "SCHOOL", "ENTERPRISE", "MALL"}
MAX_LIMIT = 1000


def _site(row: sqlite3.Row) -> Site:
    return Site(
        critical_site_id=row["critical_site_id"],
        name=row["name"],
        kind=row["kind"],
        state=row["state"],
        lat=row["lat"],
        lng=row["lng"],
        priority=row["priority"],
        emergency_service=bool(row["emergency_service"]),
        sla_customer=row["kind"] == "ENTERPRISE",
        serving_enodeb=row["serving_enodeb"],
    )


def get_site(conn: sqlite3.Connection, critical_site_id: str) -> Envelope[Site]:
    sid = parse_critical_site_id(critical_site_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM critical_site WHERE critical_site_id = ?", (sid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Critical site {sid} not found")
    return wrap(conn, source=SOURCE, tool="sites_get_site", data=_site(row), ref=sid)


def list_in_bbox(
    conn: sqlite3.Connection,
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    kind: str | None = None,
    limit: int = 200,
) -> Envelope[SiteList]:
    if not (-90 <= min_lat <= max_lat <= 90) or not (-180 <= min_lng <= max_lng <= 180):
        raise InvalidInputError("Invalid bbox: need -90<=min_lat<=max_lat<=90 and -180<=min_lng<=max_lng<=180")
    if kind is not None and kind not in KINDS:
        raise InvalidInputError(f"kind must be one of {sorted(KINDS)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    rows = conn.execute(
        "SELECT * FROM critical_site WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? "
        "AND (? IS NULL OR kind = ?) ORDER BY priority, critical_site_id LIMIT ?",
        (min_lat, max_lat, min_lng, max_lng, kind, kind, limit + 1),
    ).fetchall()
    truncated = len(rows) > limit
    sites = [_site(r) for r in rows[:limit]]
    warnings = [f"Result truncated at {limit} sites; narrow the bbox or filter by kind"] if truncated else []
    return wrap(
        conn,
        source=SOURCE,
        tool="sites_list_in_bbox",
        data=SiteList(sites=sites, returned=len(sites), truncated=truncated),
        warnings=warnings,
    )


def sites_for_tower(conn: sqlite3.Connection, enodeb_name: str) -> Envelope[TowerSites]:
    name = parse_enodeb(enodeb_name)
    if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
        raise NotFoundError(f"Tower {name} not found")
    rows = conn.execute(
        "SELECT * FROM critical_site WHERE serving_enodeb = ? ORDER BY priority, critical_site_id", (name,)
    ).fetchall()
    sites = [_site(r) for r in rows]
    data = TowerSites(
        enodeb_name=name,
        sites=sites,
        counts_by_kind=dict(Counter(s.kind for s in sites)),
        emergency_sites=sum(s.emergency_service for s in sites),
        sla_customers=sum(s.sla_customer for s in sites),
    )
    return wrap(conn, source=SOURCE, tool="sites_for_tower", data=data, ref=name)