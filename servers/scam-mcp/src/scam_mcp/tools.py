"""scam-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Read-only: it owns no tables. Reads `scam_pattern`, `scam_signal`, `tower`, `tower_subscribers`. Counts only: nothing here
identifies a person, a number, a sender or a message; patterns are generic, with no real brand or link. A pattern with fewer
than 5 reports in the window is withheld, like the other aggregates. All numbers are synthetic.

A shield blocks scam messages for the customers who turn it on: `SHIELD_ADOPTION` of the customers in an area. The loss it
avoids is the blocked attempts times the share of attempts that would have succeeded times an average loss, all stated
constants (invented), so the figure is an estimate and says so.
"""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km

from scam_mcp.models import Centre, Hotspot, Hotspots, Pattern, Protection, Trend

SOURCE = "scam-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
MIN_REPORTS = 5
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
MIN_WINDOW_MIN, MAX_WINDOW_MIN = 60, 1440
SHIELD_ADOPTION = 0.6
SUCCESS_RATE = 0.02  # synthetic: the share of blocked attempts that would have worked
AVG_LOSS_RM = 1800.0  # synthetic
PROTECTION_WINDOW_HOURS = 24
RISING, FALLING = 1.15, 0.85


def _check_circle(lat: float, lng: float, radius_km: float) -> None:
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")


def _towns_in(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float) -> tuple[list[str], list[str]]:
    """(towns, towers) that have a tower inside the circle."""
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    towns: set[str] = set()
    towers: list[str] = []
    for r in conn.execute(
        "SELECT enodeb_name, town, lat, lng FROM tower WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (max(min_lat, -90.0), min(max_lat, 90.0), max(min_lng, -180.0), min(max_lng, 180.0)),
    ):
        if haversine_km(lat, lng, r["lat"], r["lng"]) <= radius_km:
            towns.add(r["town"])
            towers.append(r["enodeb_name"])
    return sorted(towns), towers


def _sum(conn: sqlite3.Connection, pattern_id: str, towns: list[str], start: int, end: int) -> tuple[int, int]:
    marks = ", ".join("?" for _ in towns)
    row = conn.execute(
        f"SELECT COALESCE(SUM(reports), 0), COALESCE(SUM(blocked), 0) FROM scam_signal WHERE pattern_id = ? AND town IN ({marks}) AND t_min > ? AND t_min <= ?",
        [pattern_id, *towns, start, end],
    ).fetchone()
    return int(row[0]), int(row[1])


def get_hotspots(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 30.0, window_min: int = 360) -> Envelope[Hotspots]:
    """Scam patterns in a circle ranked by reports in the last window, with the trend and the blocked count."""
    _check_circle(lat, lng, radius_km)
    if not MIN_WINDOW_MIN <= window_min <= MAX_WINDOW_MIN:
        raise InvalidInputError(f"window_min must be between {MIN_WINDOW_MIN} and {MAX_WINDOW_MIN}")
    now = clock.now_min(conn)
    towns, _ = _towns_in(conn, lat, lng, radius_km)
    patterns: list[Hotspot] = []
    withheld_patterns = withheld_reports = 0
    if towns:
        half = window_min // 2
        for p in conn.execute("SELECT * FROM scam_pattern ORDER BY pattern_id"):
            reports, blocked = _sum(conn, p["pattern_id"], towns, now - window_min, now)
            if reports == 0:
                continue
            if reports < MIN_REPORTS:
                withheld_patterns += 1
                withheld_reports += reports
                continue
            first, _ = _sum(conn, p["pattern_id"], towns, now - window_min, now - half)
            second, _ = _sum(conn, p["pattern_id"], towns, now - half, now)
            trend: Trend = "RISING" if second > first * RISING else "FALLING" if second < first * FALLING else "STEADY"
            patterns.append(
                Hotspot(pattern_id=p["pattern_id"], name=p["name"], kind=p["kind"], severity=p["severity"], reports=reports, blocked=blocked, trend=trend)
            )
    patterns.sort(key=lambda h: (-h.reports, h.pattern_id))
    data = Hotspots(
        center=Centre(lat=lat, lng=lng), radius_km=radius_km, window_min=window_min, towns=towns, patterns=patterns,
        total_reports=sum(h.reports for h in patterns) + withheld_reports, withheld_patterns=withheld_patterns, withheld_reports=withheld_reports,
    )
    warnings = [] if towns else ["No towers (so no towns) inside this circle: nothing to report. Try a larger radius."]
    if withheld_patterns:
        warnings.append(f"{withheld_patterns} pattern(s) with fewer than {MIN_REPORTS} reports are withheld.")
    return wrap(conn, source=SOURCE, tool="scam_get_hotspots", data=data, ref=f"{lat},{lng},{radius_km}km/{window_min}min", warnings=warnings)


def get_pattern(conn: sqlite3.Connection, pattern_id: str) -> Envelope[Pattern]:
    """A scam pattern: what it looks like (generic), how serious it is, and the advice to give customers."""
    row = conn.execute("SELECT * FROM scam_pattern WHERE pattern_id = ?", (pattern_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Pattern {pattern_id} not found")
    data = Pattern(pattern_id=row["pattern_id"], name=row["name"], kind=row["kind"], severity=row["severity"], example=row["example"], advice=row["advice"])
    return wrap(conn, source=SOURCE, tool="scam_get_pattern", data=data, ref=pattern_id)


def estimate_protection(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 30.0) -> Envelope[Protection]:
    """For a circle: the customers a shield would protect, the messages it would have blocked in a day, and an estimated loss avoided."""
    _check_circle(lat, lng, radius_km)
    now = clock.now_min(conn)
    towns, towers = _towns_in(conn, lat, lng, radius_km)
    customers = 0
    if towers:
        marks = ", ".join("?" for _ in towers)
        customers = int(conn.execute(f"SELECT COALESCE(SUM(subscribers_est), 0) FROM tower_subscribers WHERE enodeb_name IN ({marks})", towers).fetchone()[0])
    blocked = 0
    if towns:
        marks = ", ".join("?" for _ in towns)
        blocked = int(
            conn.execute(
                f"SELECT COALESCE(SUM(blocked), 0) FROM scam_signal WHERE town IN ({marks}) AND t_min > ? AND t_min <= ?",
                [*towns, now - PROTECTION_WINDOW_HOURS * 60, now],
            ).fetchone()[0]
        )
    data = Protection(
        center=Centre(lat=lat, lng=lng), radius_km=radius_km, customers_in_area=customers, customers_protected=round(customers * SHIELD_ADOPTION),
        messages_blocked=blocked, loss_avoided_rm=round(blocked * SUCCESS_RATE * AVG_LOSS_RM, 2), window_hours=PROTECTION_WINDOW_HOURS,
    )
    return wrap(conn, source=SOURCE, tool="scam_estimate_protection", data=data, ref=f"{lat},{lng},{radius_km}km")
