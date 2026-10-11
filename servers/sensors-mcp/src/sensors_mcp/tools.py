"""sensors-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Read-only: it owns no tables. Reads `iot_sensor`, `iot_reading`. The sensors are fictional and the readings invented; the
water-level ones follow the local river gauge, so the Kuala Krai sensors rise with the flood. An alert is a sensor over
its warning level; its trend is the change over the last hour and the projected time to the danger level is a straight
line from that trend (none when the value is steady or falling, 0 when it is already past danger).
"""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km

from sensors_mcp.models import (
    Alert,
    AlertList,
    Centre,
    ReadingPoint,
    Readings,
    SensorList,
    SensorView,
    Status,
)

SOURCE = "sensors-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
KINDS = ("WATER_LEVEL", "RAIN", "AIR_QUALITY")
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
MIN_WINDOW_MIN, MAX_WINDOW_MIN = 5, 1440
TREND_WINDOW_MIN = 60
FLAT_PER_HOUR = 0.01
MAX_SENSORS = 200


def _check_circle(lat: float, lng: float, radius_km: float, kind: str | None) -> None:
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")
    if kind is not None and kind not in KINDS:
        raise InvalidInputError(f"kind must be one of {list(KINDS)}")


def _status(value: float, warn: float, danger: float) -> Status:
    return "DANGER" if value >= danger else "WARNING" if value >= warn else "OK"


def _latest(conn: sqlite3.Connection, sensor_id: str, now: int) -> sqlite3.Row | None:
    return conn.execute(  # type: ignore[no-any-return]
        "SELECT t_min, value FROM iot_reading WHERE sensor_id = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (sensor_id, now)
    ).fetchone()


def _in_circle(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float, kind: str | None) -> list[tuple[sqlite3.Row, float]]:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    found: list[tuple[sqlite3.Row, float]] = []
    for row in conn.execute(
        "SELECT * FROM iot_sensor WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? AND (? IS NULL OR kind = ?) ORDER BY sensor_id",
        (max(min_lat, -90.0), min(max_lat, 90.0), max(min_lng, -180.0), min(max_lng, 180.0), kind, kind),
    ):
        distance = haversine_km(lat, lng, row["lat"], row["lng"])
        if distance <= radius_km:
            found.append((row, distance))
    return found


def list_in_area(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 20.0, kind: str | None = None) -> Envelope[SensorList]:
    """Sensors in a circle with their latest reading and status, nearest first."""
    _check_circle(lat, lng, radius_km, kind)
    now = clock.now_min(conn)
    views: list[SensorView] = []
    for row, distance in sorted(_in_circle(conn, lat, lng, radius_km, kind), key=lambda pair: (pair[1], pair[0]["sensor_id"]))[:MAX_SENSORS]:
        latest = _latest(conn, row["sensor_id"], now)
        if latest is None:
            continue
        views.append(
            SensorView(
                sensor_id=row["sensor_id"], kind=row["kind"], name=row["name"], owner=row["owner"], town=row["town"], enodeb_name=row["enodeb_name"],
                lat=row["lat"], lng=row["lng"], unit=row["unit"], value=latest["value"], at=clock.iso_at(conn, latest["t_min"]),
                status=_status(latest["value"], row["warn_value"], row["danger_value"]), distance_km=round(distance, 2),
            )
        )
    data = SensorList(center=Centre(lat=lat, lng=lng), radius_km=radius_km, sensors=views, returned=len(views))
    return wrap(conn, source=SOURCE, tool="sensors_list_in_area", data=data, ref=f"{lat},{lng},{radius_km}km")


def get_readings(conn: sqlite3.Connection, sensor_id: str, window_min: int = 360) -> Envelope[Readings]:
    """One sensor's readings over the last window_min minutes, up to the scenario clock."""
    if not MIN_WINDOW_MIN <= window_min <= MAX_WINDOW_MIN:
        raise InvalidInputError(f"window_min must be between {MIN_WINDOW_MIN} and {MAX_WINDOW_MIN}")
    sensor = conn.execute("SELECT * FROM iot_sensor WHERE sensor_id = ?", (sensor_id,)).fetchone()
    if sensor is None:
        raise NotFoundError(f"Sensor {sensor_id} not found")
    now = clock.now_min(conn)
    rows = conn.execute(
        "SELECT t_min, value FROM iot_reading WHERE sensor_id = ? AND t_min BETWEEN ? AND ? ORDER BY t_min", (sensor_id, now - window_min, now)
    ).fetchall()
    if not rows:
        raise NotFoundError(f"Sensor {sensor_id} has no readings in that window")
    points = [ReadingPoint(t_min=r["t_min"], at=clock.iso_at(conn, r["t_min"]), value=r["value"]) for r in rows]
    values = [p.value for p in points]
    data = Readings(
        sensor_id=sensor_id, kind=sensor["kind"], name=sensor["name"], unit=sensor["unit"], window_min=window_min, points=points,
        latest=values[-1], min_value=min(values), max_value=max(values),
    )
    return wrap(conn, source=SOURCE, tool="sensors_get_readings", data=data, ref=sensor_id)


def _trend(conn: sqlite3.Connection, sensor_id: str, now: int, latest: float) -> float:
    earlier = conn.execute(
        "SELECT value FROM iot_reading WHERE sensor_id = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (sensor_id, now - TREND_WINDOW_MIN)
    ).fetchone()
    return round(latest - earlier["value"], 3) if earlier is not None else 0.0


def get_alerts(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 20.0, kind: str | None = None) -> Envelope[AlertList]:
    """Sensors over their warning level, most urgent first, with the trend and the projected time to the danger level."""
    _check_circle(lat, lng, radius_km, kind)
    now = clock.now_min(conn)
    alerts: list[Alert] = []
    for row, distance in _in_circle(conn, lat, lng, radius_km, kind):
        latest = _latest(conn, row["sensor_id"], now)
        if latest is None:
            continue
        status = _status(latest["value"], row["warn_value"], row["danger_value"])
        if status == "OK":
            continue
        trend = _trend(conn, row["sensor_id"], now, latest["value"])
        if status == "DANGER":
            projected: int | None = 0
        elif trend > FLAT_PER_HOUR:
            projected = round((row["danger_value"] - latest["value"]) / trend * 60)
        else:
            projected = None
        alerts.append(
            Alert(
                sensor_id=row["sensor_id"], kind=row["kind"], name=row["name"], owner=row["owner"], town=row["town"], unit=row["unit"],
                value=latest["value"], warn_value=row["warn_value"], danger_value=row["danger_value"], status=status, trend_per_hour=trend,
                projected_min_to_danger=projected, distance_km=round(distance, 2),
            )
        )
    alerts.sort(
        key=lambda a: (
            0 if a.status == "DANGER" else 1,
            -a.value / a.danger_value if a.status == "DANGER" else (a.projected_min_to_danger if a.projected_min_to_danger is not None else 10**9),
            a.sensor_id,
        )
    )
    data = AlertList(center=Centre(lat=lat, lng=lng), radius_km=radius_km, alerts=alerts, returned=len(alerts))
    return wrap(conn, source=SOURCE, tool="sensors_get_alerts", data=data, ref=f"{lat},{lng},{radius_km}km")
