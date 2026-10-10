"""weather-mcp tool logic. Read-only. Observations come from the station nearest the requested point."""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km

from weather_mcp.models import (
    Intensity,
    Lightning,
    LightningActivity,
    Rainfall,
    RainPoint,
    StationRef,
)

SOURCE = "weather-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
MIN_WINDOW_MIN, MAX_WINDOW_MIN = 60, 1440
DEFAULT_RADIUS_KM = 30.0
# Invented demo thresholds on 24 h rainfall (mm). Not real warning criteria.
HEAVY_MM, VERY_HEAVY_MM, EXTREME_MM = 60.0, 120.0, 180.0


def intensity_for(rain_24h_mm: float) -> Intensity:
    if rain_24h_mm >= EXTREME_MM:
        return "EXTREME"
    if rain_24h_mm >= VERY_HEAVY_MM:
        return "VERY_HEAVY"
    if rain_24h_mm >= HEAVY_MM:
        return "HEAVY"
    return "NORMAL"


def activity_for(last_hour_strikes: int) -> LightningActivity:
    if last_hour_strikes >= 100:
        return "SEVERE"
    if last_hour_strikes >= 20:
        return "HIGH"
    if last_hour_strikes > 0:
        return "LOW"
    return "NONE"


def _validate(lat: float, lng: float, window_min: int, radius_km: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        raise InvalidInputError("lat must be in -90..90 and lng in -180..180")
    if not MIN_WINDOW_MIN <= window_min <= MAX_WINDOW_MIN:
        raise InvalidInputError(f"window_min must be between {MIN_WINDOW_MIN} and {MAX_WINDOW_MIN}")
    if not 1 <= radius_km <= 100:
        raise InvalidInputError("radius_km must be between 1 and 100")


def _nearest_station(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float) -> StationRef:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    rows = conn.execute(
        "SELECT * FROM weather_station WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ?",
        (min_lat, max_lat, min_lng, max_lng),
    ).fetchall()
    scored = sorted((haversine_km(lat, lng, r["lat"], r["lng"]), r["station_id"]) for r in rows)
    if not scored or scored[0][0] > radius_km:
        raise NotFoundError(f"No weather station within {radius_km:g} km of ({lat}, {lng})")
    distance, station_id = scored[0]
    row = next(r for r in rows if r["station_id"] == station_id)
    return StationRef(
        station_id=station_id,
        name=row["name"],
        lat=row["lat"],
        lng=row["lng"],
        distance_km=round(distance, 2),
    )


def _observations(conn: sqlite3.Connection, station_id: str, window_min: int) -> list[sqlite3.Row]:
    now = clock.now_min(conn)
    return conn.execute(
        "SELECT * FROM weather_obs WHERE station_id = ? AND t_min > ? AND t_min <= ? ORDER BY t_min",
        (station_id, now - window_min, now),
    ).fetchall()


def get_rainfall(
    conn: sqlite3.Connection,
    lat: float,
    lng: float,
    window_min: int = MAX_WINDOW_MIN,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> Envelope[Rainfall]:
    _validate(lat, lng, window_min, radius_km)
    station = _nearest_station(conn, lat, lng, radius_km)
    rows = _observations(conn, station.station_id, window_min)
    day = _observations(conn, station.station_id, MAX_WINDOW_MIN)
    rain_24h = round(sum(r["rain_mm"] for r in day), 1)
    data = Rainfall(
        station=station,
        window_min=window_min,
        total_mm=round(sum(r["rain_mm"] for r in rows), 1),
        last_hour_mm=rows[-1]["rain_mm"] if rows else 0.0,
        peak_mm_per_hour=max((r["rain_mm"] for r in rows), default=0.0),
        rain_24h_mm=rain_24h,
        intensity=intensity_for(rain_24h),
        points=[
            RainPoint(
                t_min=r["t_min"],
                at=clock.iso_at(conn, r["t_min"]),
                rain_mm=r["rain_mm"],
                lightning_strikes=r["lightning"],
            )
            for r in rows
        ],
    )
    warnings = [] if rows else ["No observations in this window at the current scenario time"]
    return wrap(
        conn, source=SOURCE, tool="weather_get_rainfall", data=data, ref=station.station_id, warnings=warnings
    )


def get_lightning(
    conn: sqlite3.Connection,
    lat: float,
    lng: float,
    window_min: int = MIN_WINDOW_MIN,
    radius_km: float = DEFAULT_RADIUS_KM,
) -> Envelope[Lightning]:
    _validate(lat, lng, window_min, radius_km)
    station = _nearest_station(conn, lat, lng, radius_km)
    rows = _observations(conn, station.station_id, window_min)
    last_hour = rows[-1]["lightning"] if rows else 0
    data = Lightning(
        station=station,
        window_min=window_min,
        total_strikes=sum(r["lightning"] for r in rows),
        last_hour_strikes=last_hour,
        peak_strikes_per_hour=max((r["lightning"] for r in rows), default=0),
        activity=activity_for(last_hour),
    )
    warnings = [] if rows else ["No observations in this window at the current scenario time"]
    return wrap(
        conn, source=SOURCE, tool="weather_get_lightning", data=data, ref=station.station_id, warnings=warnings
    )
