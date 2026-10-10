"""user-mcp tool logic. Read-only. Subscribers are identified only by msisdn_hash; location is cell-level."""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km
from menara_core.ids import parse_enodeb, parse_msisdn_hash
from menara_core.privacy import MIN_AGGREGATE_COUNT

from user_mcp.models import (
    AreaSubscriber,
    Centre,
    ExperienceLabel,
    ExperiencePoint,
    ExperienceSummary,
    ExperienceWindow,
    ServingCell,
    SubscriberList,
    TowerSubscribers,
    Trail,
    TrailSegment,
)

SOURCE = "user-mcp"
MAX_WINDOW_MIN = 1440
MAX_TRAIL_WINDOW_MIN = 2880
MAX_LIST_LIMIT = 500
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
# Where each subscriber is at the scenario clock: their latest visit that has started.
_CURRENT_CELL = (
    "SELECT v.msisdn_hash, v.serving_cell, v.enodeb_name, v.cell_lat, v.cell_lng FROM subscriber_cell_visit v "
    "WHERE v.start_min = (SELECT MAX(x.start_min) FROM subscriber_cell_visit x "
    "WHERE x.msisdn_hash = v.msisdn_hash AND x.start_min <= :now)"
)
_SEVERITY: dict[ExperienceLabel, int] = {"NO_SERVICE": 0, "POOR": 1, "FAIR": 2, "GOOD": 3}


def label_for(score: float, throughput_mbps: float) -> ExperienceLabel:
    if throughput_mbps <= 0.0 and score <= 0.0:
        return "NO_SERVICE"
    if score < 40:
        return "POOR"
    if score < 70:
        return "FAIR"
    return "GOOD"


def _worst_label(points: list[ExperiencePoint]) -> ExperienceLabel | None:
    if not points:
        return None
    return min((p.label for p in points), key=lambda label: _SEVERITY[label])


def _subscriber(conn: sqlite3.Connection, msisdn_hash: str) -> sqlite3.Row:
    digest = parse_msisdn_hash(msisdn_hash)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM subscriber WHERE msisdn_hash = ?", (digest,)).fetchone()
    if row is None:
        raise NotFoundError(f"Subscriber {digest} not found")
    return row


def _point(conn: sqlite3.Connection, row: sqlite3.Row) -> ExperiencePoint:
    return ExperiencePoint(
        t_min=row["t_min"],
        at=clock.iso_at(conn, row["t_min"]),
        score=row["score"],
        label=label_for(row["score"], row["throughput_mbps"]),
        throughput_mbps=row["throughput_mbps"],
        drop_events=row["drop_events"],
        rsrp_dbm=row["rsrp_dbm"],
    )


def get_serving_cell(conn: sqlite3.Connection, msisdn_hash: str) -> Envelope[ServingCell]:
    sub = _subscriber(conn, msisdn_hash)
    now = clock.now_min(conn)
    state = conn.execute(
        "SELECT t_min, attached FROM subscriber_state WHERE msisdn_hash = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (sub["msisdn_hash"], now),
    ).fetchone()
    attached = bool(state["attached"]) if state else True
    visit = conn.execute(
        "SELECT serving_cell, enodeb_name, cell_lat, cell_lng FROM subscriber_cell_visit "
        "WHERE msisdn_hash = ? AND start_min <= ? ORDER BY start_min DESC LIMIT 1",
        (sub["msisdn_hash"], now),
    ).fetchone()
    where = visit if visit is not None else sub  # the trail says where they are now; the row is the fallback
    data = ServingCell(
        msisdn_hash=sub["msisdn_hash"],
        serving_cell=where["serving_cell"],
        enodeb_name=where["enodeb_name"],
        attached=attached,
        detached_since=None if attached or state is None else clock.iso_at(conn, state["t_min"]),
        cell_lat=where["cell_lat"],
        cell_lng=where["cell_lng"],
        plan=sub["plan"],
        segment=sub["segment"],
        home_fibre=bool(sub["home_fibre"]),
    )
    warnings = [] if attached else ["Subscriber is not attached; serving_cell is the last known cell"]
    return wrap(
        conn, source=SOURCE, tool="user_get_serving_cell", data=data, ref=sub["msisdn_hash"], warnings=warnings
    )


def get_experience(
    conn: sqlite3.Connection, msisdn_hash: str, window_min: int = 120
) -> Envelope[ExperienceWindow]:
    sub = _subscriber(conn, msisdn_hash)
    if not 5 <= window_min <= MAX_WINDOW_MIN:
        raise InvalidInputError(f"window_min must be between 5 and {MAX_WINDOW_MIN}")
    now = clock.now_min(conn)
    digest = sub["msisdn_hash"]
    rows = conn.execute(
        "SELECT * FROM subscriber_experience WHERE msisdn_hash = ? AND t_min > ? AND t_min <= ? ORDER BY t_min",
        (digest, now - window_min, now),
    ).fetchall()
    latest_row = conn.execute(
        "SELECT * FROM subscriber_experience WHERE msisdn_hash = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (digest, now),
    ).fetchone()
    points = [_point(conn, r) for r in rows]
    summary = ExperienceSummary(
        samples=len(points),
        avg_score=round(sum(p.score for p in points) / len(points), 1) if points else None,
        min_score=min((p.score for p in points), default=None),
        worst_label=_worst_label(points),
    )
    warnings = [] if points else ["No samples in this window; see `latest` for the most recent one"]
    return wrap(
        conn,
        source=SOURCE,
        tool="user_get_experience",
        data=ExperienceWindow(
            msisdn_hash=digest,
            window_min=window_min,
            latest=_point(conn, latest_row) if latest_row else None,
            points=points,
            summary=summary,
        ),
        ref=digest,
        warnings=warnings,
    )


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_LIST_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIST_LIMIT}")


def _attached(conn: sqlite3.Connection, digest: str, now: int) -> bool:
    state = conn.execute(
        "SELECT attached FROM subscriber_state WHERE msisdn_hash = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (digest, now),
    ).fetchone()
    return bool(state["attached"]) if state else True


def _latest_label(conn: sqlite3.Connection, digest: str, now: int) -> ExperienceLabel | None:
    row = conn.execute(
        "SELECT score, throughput_mbps FROM subscriber_experience WHERE msisdn_hash = ? AND t_min <= ? "
        "ORDER BY t_min DESC LIMIT 1",
        (digest, now),
    ).fetchone()
    return label_for(row["score"], row["throughput_mbps"]) if row else None


def _subscriber_list(
    conn: sqlite3.Connection,
    rows: list[sqlite3.Row],
    now: int,
    limit: int,
    *,
    tool: str,
    ref: str,
    center: Centre | None = None,
    radius_km: float | None = None,
    enodeb_name: str | None = None,
) -> Envelope[SubscriberList]:
    rows = sorted(rows, key=lambda r: (r["enodeb_name"], r["msisdn_hash"]))
    total = len(rows)
    if 0 < total < MIN_AGGREGATE_COUNT:
        withheld = SubscriberList(
            center=center,
            radius_km=radius_km,
            enodeb_name=enodeb_name,
            towers=[],
            subscribers=[],
            subscribers_total=None,
            returned=0,
            truncated=False,
            withheld=True,
        )
        warning = f"Fewer than {MIN_AGGREGATE_COUNT} subscribers match; the list is withheld to protect individuals"
        return wrap(conn, source=SOURCE, tool=tool, data=withheld, ref=ref, warnings=[warning])
    per_tower: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        per_tower.setdefault(r["enodeb_name"], []).append(r)
    towers = []
    for name, group in per_tower.items():
        est = conn.execute("SELECT subscribers_est FROM tower_subscribers WHERE enodeb_name = ?", (name,)).fetchone()
        towers.append(
            TowerSubscribers(
                enodeb_name=name,
                cell_lat=group[0]["cell_lat"],
                cell_lng=group[0]["cell_lng"],
                subscribers_sampled=len(group),
                subscribers_est=est["subscribers_est"] if est else None,
            )
        )
    shown = [
        AreaSubscriber(
            msisdn_hash=r["msisdn_hash"],
            serving_cell=r["serving_cell"],
            enodeb_name=r["enodeb_name"],
            cell_lat=r["cell_lat"],
            cell_lng=r["cell_lng"],
            attached=_attached(conn, r["msisdn_hash"], now),
            latest_label=_latest_label(conn, r["msisdn_hash"], now),
        )
        for r in rows[:limit]
    ]
    truncated = total > limit
    warnings = [f"Showing {limit} of {total} sampled subscribers; counts per tower cover all of them"] if truncated else []
    data = SubscriberList(
        center=center,
        radius_km=radius_km,
        enodeb_name=enodeb_name,
        towers=towers,
        subscribers=shown,
        subscribers_total=total,
        returned=len(shown),
        truncated=truncated,
        withheld=False,
    )
    return wrap(conn, source=SOURCE, tool=tool, data=data, ref=ref, warnings=warnings)


def list_on_tower(conn: sqlite3.Connection, enodeb_name: str, limit: int = 200) -> Envelope[SubscriberList]:
    """Sampled synthetic subscribers on one tower right now, with the tower's population estimate."""
    name = parse_enodeb(enodeb_name)
    _validate_limit(limit)
    if conn.execute("SELECT 1 FROM tower_subscribers WHERE enodeb_name = ?", (name,)).fetchone() is None:
        raise NotFoundError(f"Tower {name} not found")
    now = clock.now_min(conn)
    rows = conn.execute(f"SELECT * FROM ({_CURRENT_CELL}) WHERE enodeb_name = :name", {"now": now, "name": name}).fetchall()
    return _subscriber_list(conn, rows, now, limit, tool="user_list_on_tower", ref=name, enodeb_name=name)


def list_in_area(
    conn: sqlite3.Connection, lat: float, lng: float, radius_km: float, limit: int = 200
) -> Envelope[SubscriberList]:
    """Sampled synthetic subscribers whose serving tower is inside the circle right now."""
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")
    _validate_limit(limit)
    now = clock.now_min(conn)
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    candidates = conn.execute(
        f"SELECT * FROM ({_CURRENT_CELL}) WHERE cell_lat BETWEEN :min_lat AND :max_lat "
        "AND cell_lng BETWEEN :min_lng AND :max_lng",
        {"now": now, "min_lat": min_lat, "max_lat": max_lat, "min_lng": min_lng, "max_lng": max_lng},
    ).fetchall()
    inside = [r for r in candidates if haversine_km(lat, lng, r["cell_lat"], r["cell_lng"]) <= radius_km]
    return _subscriber_list(
        conn,
        inside,
        now,
        limit,
        tool="user_list_in_area",
        ref=f"{lat},{lng}",
        center=Centre(lat=lat, lng=lng),
        radius_km=radius_km,
    )


def get_trail(conn: sqlite3.Connection, msisdn_hash: str, window_min: int = 1440) -> Envelope[Trail]:
    """The cells a subscriber has been on, up to the scenario clock, with arrival and leave times (cell level)."""
    sub = _subscriber(conn, msisdn_hash)
    if not 5 <= window_min <= MAX_TRAIL_WINDOW_MIN:
        raise InvalidInputError(f"window_min must be between 5 and {MAX_TRAIL_WINDOW_MIN}")
    now = clock.now_min(conn)
    window_start = now - window_min
    visits = conn.execute(
        "SELECT start_min, serving_cell, enodeb_name, cell_lat, cell_lng FROM subscriber_cell_visit "
        "WHERE msisdn_hash = ? AND start_min <= ? ORDER BY start_min",
        (sub["msisdn_hash"], now),
    ).fetchall()
    segments: list[TrailSegment] = []
    for index, visit in enumerate(visits):
        following = visits[index + 1]["start_min"] if index + 1 < len(visits) else None
        if following is not None and following <= window_start:
            continue  # ended before the window began
        segments.append(
            TrailSegment(
                serving_cell=visit["serving_cell"],
                enodeb_name=visit["enodeb_name"],
                cell_lat=visit["cell_lat"],
                cell_lng=visit["cell_lng"],
                arrived_at=clock.iso_at(conn, visit["start_min"]),
                left_at=None if following is None else clock.iso_at(conn, following),
                duration_min=(now if following is None else following) - max(visit["start_min"], window_start),
                current=following is None,
            )
        )
    data = Trail(
        msisdn_hash=sub["msisdn_hash"],
        window_min=window_min,
        segments=segments,
        moves=max(0, len(segments) - 1),
        distinct_towers=len({s.enodeb_name for s in segments}),
    )
    warnings = [] if segments else ["No location history for this subscriber in the window"]
    return wrap(conn, source=SOURCE, tool="user_get_trail", data=data, ref=sub["msisdn_hash"], warnings=warnings)
