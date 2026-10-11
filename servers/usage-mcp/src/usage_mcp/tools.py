"""usage-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Reads (read-only, base tables written by the seed): `tower`, `tower_subscribers`, `app`, `app_hour_factor`,
`tower_app_share`. Owns no tables. Everything is aggregated per tower or per circle; there is no per-person data.
All numbers are synthetic estimates.

For one app, users in an hour = sum over the towers of (the tower's estimated users x the share of them who use the app
in a day x the share of its daily users online with it in that hour, about 40% at the peak). The data share in an hour weights each app's share of a tower's
data by the same hourly activity and renormalises.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km

from usage_mcp.models import (
    AppTrend,
    AppUsage,
    AreaUsage,
    CategoryShare,
    Centre,
    TrendPoint,
)

SOURCE = "usage-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
MIN_ESTIMATED_USERS = 5
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
MAX_LIMIT = 20
RANKS = ("users", "data")
HOURS = range(24)
NO_TOWERS = "No towers inside this circle, so there is nothing to describe; try a larger radius."

Base = dict[str, tuple[float, float]]  # app_id -> (daily users, data weight) summed over the towers


def withhold(total_users: int) -> bool:
    """An area this small is not described (the same rule as the subscriber lists)."""
    return total_users < MIN_ESTIMATED_USERS


def _check(lat: float, lng: float, radius_km: float) -> None:
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")


def _check_view(hour: int | None, limit: int, rank_by: str) -> None:
    if hour is not None and hour not in HOURS:
        raise InvalidInputError("hour must be between 0 and 23")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    if rank_by not in RANKS:
        raise InvalidInputError(f"rank_by must be one of {list(RANKS)}")


def _hour(conn: sqlite3.Connection, hour: int | None) -> int:
    return hour if hour is not None else datetime.fromisoformat(clock.as_of(conn)).hour


def _catalogue(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    return {r["app_id"]: (r["name"], r["category"]) for r in conn.execute("SELECT app_id, name, category FROM app ORDER BY app_id")}


def _factors(conn: sqlite3.Connection) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    for r in conn.execute("SELECT app_id, hour, factor FROM app_hour_factor ORDER BY app_id, hour"):
        out.setdefault(r["app_id"], []).append(r["factor"])
    return out


def _towers_in(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float) -> list[str]:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    rows = conn.execute(
        "SELECT enodeb_name, lat, lng FROM tower WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? ORDER BY enodeb_name",
        (max(min_lat, -90.0), min(max_lat, 90.0), max(min_lng, -180.0), min(max_lng, 180.0)),
    ).fetchall()
    return [r["enodeb_name"] for r in rows if haversine_km(lat, lng, r["lat"], r["lng"]) <= radius_km]


def _aggregate(conn: sqlite3.Connection, towers: list[str]) -> tuple[int, Base]:
    if not towers:
        return 0, {}
    marks = ", ".join("?" for _ in towers)
    total = conn.execute(f"SELECT COALESCE(SUM(subscribers_est), 0) FROM tower_subscribers WHERE enodeb_name IN ({marks})", towers).fetchone()[0]
    base: Base = {}
    for r in conn.execute(
        "SELECT s.app_id, SUM(u.subscribers_est * s.user_share) AS users, SUM(u.subscribers_est * s.data_share) AS data "
        "FROM tower_app_share s JOIN tower_subscribers u ON u.enodeb_name = s.enodeb_name "
        f"WHERE s.enodeb_name IN ({marks}) GROUP BY s.app_id",
        towers,
    ):
        base[r["app_id"]] = (r["users"], r["data"])
    return int(total), base


def _usage(
    conn: sqlite3.Connection,
    towers: list[str],
    hour: int,
    rank_by: str,
    limit: int,
    *,
    centre: Centre | None,
    radius_km: float | None,
    tower: str | None,
) -> AreaUsage:
    total, base = _aggregate(conn, towers)
    empty = AreaUsage(
        center=centre, radius_km=radius_km, enodeb_name=tower, hour=hour, rank_by=rank_by, towers_counted=len(towers),
        total_users_est=total, withheld=bool(towers) and withhold(total), apps=[], categories=[], busiest_hour=None,
    )
    if not towers or withhold(total):
        return empty
    names, factors = _catalogue(conn), _factors(conn)
    users_h = {a: base[a][0] * factors[a][hour] for a in base}
    data_h = {a: base[a][1] * factors[a][hour] for a in base}
    data_total = sum(data_h.values()) or 1.0
    ranked = sorted(base, key=lambda a: (-(users_h[a] if rank_by == "users" else data_h[a]), a))[:limit]
    apps = [
        AppUsage(
            rank=i, app_id=a, name=names[a][0], category=names[a][1], users_est=round(users_h[a]),
            reach_pct=round(users_h[a] / total * 100, 1), data_share_pct=round(data_h[a] / data_total * 100, 1),
        )
        for i, a in enumerate(ranked, start=1)
    ]
    by_category: dict[str, float] = {}
    for a, volume in data_h.items():
        by_category[names[a][1]] = by_category.get(names[a][1], 0.0) + volume
    categories = [
        CategoryShare(category=c, data_share_pct=round(v / data_total * 100, 2))
        for c, v in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    busiest = max(HOURS, key=lambda h: (sum(base[a][0] * factors[a][h] for a in base), -h))
    return empty.model_copy(update={"apps": apps, "categories": categories, "busiest_hour": busiest})


def top_apps_in_area(
    conn: sqlite3.Connection,
    lat: float,
    lng: float,
    radius_km: float = 10.0,
    rank_by: str = "users",
    hour: int | None = None,
    limit: int = 10,
) -> Envelope[AreaUsage]:
    """The apps people in a circle use, ranked by users or by data, with the category split and the busiest hour."""
    _check(lat, lng, radius_km)
    _check_view(hour, limit, rank_by)
    used = _hour(conn, hour)
    towers = _towers_in(conn, lat, lng, radius_km)
    data = _usage(conn, towers, used, rank_by, limit, centre=Centre(lat=lat, lng=lng), radius_km=radius_km, tower=None)
    warnings = [] if towers else [NO_TOWERS]
    if data.withheld:
        warnings.append(f"Fewer than {MIN_ESTIMATED_USERS} estimated users in this area; usage is withheld.")
    return wrap(conn, source=SOURCE, tool="usage_top_apps_in_area", data=data, ref=f"{lat},{lng},{radius_km}km@{used:02d}h", warnings=warnings)


def get_tower_apps(
    conn: sqlite3.Connection, enodeb_name: str, rank_by: str = "users", hour: int | None = None, limit: int = 10
) -> Envelope[AreaUsage]:
    """The same view for one tower."""
    _check_view(hour, limit, rank_by)
    if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (enodeb_name,)).fetchone() is None:
        raise NotFoundError(f"Tower {enodeb_name} not found")
    used = _hour(conn, hour)
    data = _usage(conn, [enodeb_name], used, rank_by, limit, centre=None, radius_km=None, tower=enodeb_name)
    warnings = [f"Fewer than {MIN_ESTIMATED_USERS} estimated users on this tower; usage is withheld."] if data.withheld else []
    return wrap(conn, source=SOURCE, tool="usage_get_tower_apps", data=data, ref=f"{enodeb_name}@{used:02d}h", warnings=warnings)


def app_trend(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 10.0, app: str = "") -> Envelope[AppTrend]:
    """One app's users hour by hour in a circle, and its peak hour."""
    _check(lat, lng, radius_km)
    names = _catalogue(conn)
    wanted = app.strip().lower()
    app_id = next((a for a, (name, _) in names.items() if wanted in (a, name.lower())), None)
    if app_id is None:
        raise InvalidInputError(f"Unknown app {app!r}. Valid app ids: {', '.join(sorted(names))}")
    towers = _towers_in(conn, lat, lng, radius_km)
    total, base = _aggregate(conn, towers)
    hidden = not towers or withhold(total)
    factors = _factors(conn)[app_id]
    points = (
        []
        if hidden
        else [
            TrendPoint(
                hour=h,
                users_est=round(base[app_id][0] * factors[h]),
                reach_pct=round(base[app_id][0] * factors[h] / total * 100, 1),
            )
            for h in HOURS
        ]
    )
    data = AppTrend(
        app_id=app_id, name=names[app_id][0], category=names[app_id][1], center=Centre(lat=lat, lng=lng), radius_km=radius_km,
        towers_counted=len(towers), total_users_est=total, withheld=bool(towers) and hidden, points=points,
        peak_hour=max(points, key=lambda p: (p.users_est, -p.hour)).hour if points else None,
    )
    warnings = [] if towers else [NO_TOWERS]
    return wrap(conn, source=SOURCE, tool="usage_app_trend", data=data, ref=f"{app_id}@{lat},{lng},{radius_km}km", warnings=warnings)
