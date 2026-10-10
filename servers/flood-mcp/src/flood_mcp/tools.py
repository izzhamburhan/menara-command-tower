"""flood-mcp tool logic. Read-only. River gauges and the current circular flood extent."""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import haversine_km
from menara_core.ids import parse_gauge_id

from flood_mcp.models import Gauge, GaugeList, GaugePin, GaugeStatus, PointCheck, Trend

SOURCE = "flood-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
TREND_WINDOW_MIN = 180
TREND_THRESHOLD_M = 0.3
MAX_LIMIT = 500
STATUSES = {"NORMAL", "WARNING", "DANGER"}


def status_for(level_m: float | None, warning_m: float, danger_m: float) -> GaugeStatus:
    if level_m is None:
        return "NORMAL"
    if level_m >= danger_m:
        return "DANGER"
    if level_m >= warning_m:
        return "WARNING"
    return "NORMAL"


def _level_at(conn: sqlite3.Connection, gauge_id: str, t_min: int) -> float | None:
    row = conn.execute(
        "SELECT level_m FROM flood_reading WHERE gauge_id = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (gauge_id, t_min),
    ).fetchone()
    return float(row["level_m"]) if row else None


def _trend(now_level: float | None, before: float | None) -> Trend:
    if now_level is None or before is None:
        return "STEADY"
    if now_level - before > TREND_THRESHOLD_M:
        return "RISING"
    if before - now_level > TREND_THRESHOLD_M:
        return "FALLING"
    return "STEADY"


def get_gauge(conn: sqlite3.Connection, gauge_id: str) -> Envelope[Gauge]:
    gid = parse_gauge_id(gauge_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM flood_gauge WHERE gauge_id = ?", (gid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Gauge {gid} not found")
    now = clock.now_min(conn)
    level = _level_at(conn, gid, now)
    data = Gauge(
        gauge_id=gid,
        river=row["river"],
        station=row["station"],
        state=row["state"],
        lat=row["lat"],
        lng=row["lng"],
        warning_m=row["warning_m"],
        danger_m=row["danger_m"],
        level_m=level,
        status=status_for(level, row["warning_m"], row["danger_m"]),
        trend=_trend(level, _level_at(conn, gid, now - TREND_WINDOW_MIN)),
        above_danger_by_m=round(max(0.0, level - row["danger_m"]), 2) if level is not None else 0.0,
    )
    warnings = [] if level is not None else ["No reading at the current scenario time"]
    return wrap(conn, source=SOURCE, tool="flood_get_gauge", data=data, ref=gid, warnings=warnings)


def list_gauges(
    conn: sqlite3.Connection,
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    status: str | None = None,
    limit: int = 100,
) -> Envelope[GaugeList]:
    if not (-90 <= min_lat <= max_lat <= 90) or not (-180 <= min_lng <= max_lng <= 180):
        raise InvalidInputError("Invalid bbox: need -90<=min_lat<=max_lat<=90 and -180<=min_lng<=max_lng<=180")
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    now = clock.now_min(conn)
    rows = conn.execute(
        "SELECT * FROM flood_gauge WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? ORDER BY gauge_id",
        (min_lat, max_lat, min_lng, max_lng),
    ).fetchall()
    pins: list[GaugePin] = []
    for row in rows:
        level = _level_at(conn, row["gauge_id"], now)
        gauge_status = status_for(level, row["warning_m"], row["danger_m"])
        if status is None or gauge_status == status:
            pins.append(
                GaugePin(
                    gauge_id=row["gauge_id"],
                    river=row["river"],
                    state=row["state"],
                    lat=row["lat"],
                    lng=row["lng"],
                    level_m=level,
                    status=gauge_status,
                )
            )
    shown = pins[:limit]
    warnings = [f"Result truncated at {limit} gauges; narrow the bbox or filter by status"] if len(pins) > limit else []
    return wrap(
        conn,
        source=SOURCE,
        tool="flood_list_gauges",
        data=GaugeList(gauges=shown, returned=len(shown), truncated=len(pins) > limit),
        warnings=warnings,
    )


def check_point(conn: sqlite3.Connection, lat: float, lng: float) -> Envelope[PointCheck]:
    """Is this point inside the flood extent that applies at the scenario time, and how deep is it?"""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise InvalidInputError("lat must be in -90..90 and lng in -180..180")
    now = clock.now_min(conn)
    extent: sqlite3.Row | None = conn.execute(
        "SELECT * FROM flood_extent WHERE from_min <= ? ORDER BY from_min DESC LIMIT 1", (now,)
    ).fetchone()
    if extent is None:
        data = PointCheck(
            lat=lat, lng=lng, inside_flood=False, extent_id=None, extent_name=None,
            depth_m=None, distance_to_edge_km=None, extent_radius_km=None,
        )
        return wrap(
            conn, source=SOURCE, tool="flood_check_point", data=data,
            warnings=["No flood extent exists yet at the current scenario time"],
        )
    distance = haversine_km(lat, lng, extent["lat"], extent["lng"])
    inside = distance <= extent["radius_km"]
    data = PointCheck(
        lat=lat,
        lng=lng,
        inside_flood=inside,
        extent_id=extent["extent_id"],
        extent_name=extent["name"],
        depth_m=round(extent["max_depth_m"] * (1 - distance / extent["radius_km"]), 2) if inside else 0.0,
        distance_to_edge_km=0.0 if inside else round(distance - extent["radius_km"], 2),
        extent_radius_km=extent["radius_km"],
    )
    return wrap(conn, source=SOURCE, tool="flood_check_point", data=data, ref=extent["extent_id"])
