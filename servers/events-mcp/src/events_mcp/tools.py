"""events-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Read-only: it owns no tables. Reads `crowd_event`, `tower`, `tower_kpi`, `tower_subscribers`. The crowd model (how a crowd
loads the towers around a venue) is shared with exposure-mcp in `menara_core.crowd`. Events are fictional and every number
is invented. The plan is advice as data: each recommendation names the tool an agent would call next; nothing is executed.
"""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.crowd import (
    SERVING_TOWERS,
    baseline_prb,
    risk_for,
    serving_towers,
    uplift_by_tower,
)
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import haversine_km

from events_mcp.models import (
    Centre,
    Event,
    EventList,
    Forecast,
    Plan,
    Recommendation,
    TowerForecast,
)

SOURCE = "events-mcp"
OWNED_TABLES: frozenset[str] = frozenset()
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
MIN_WITHIN_MIN, MAX_WITHIN_MIN = 5, 14400
MAX_EVENTS = 100
BROADCAST_ATTENDANCE = 20000
RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def _event(conn: sqlite3.Connection, event_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM crowd_event WHERE event_id = ?", (event_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Event {event_id} not found")
    return row  # type: ignore[no-any-return]


def list_upcoming(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 30.0, within_min: int = 4320) -> Envelope[EventList]:
    """Events in a circle that are on now or start within the window, soonest first."""
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")
    if not MIN_WITHIN_MIN <= within_min <= MAX_WITHIN_MIN:
        raise InvalidInputError(f"within_min must be between {MIN_WITHIN_MIN} and {MAX_WITHIN_MIN}")
    now = clock.now_min(conn)
    events: list[Event] = []
    for row in conn.execute("SELECT * FROM crowd_event WHERE end_min > ? AND start_min <= ? ORDER BY start_min, event_id", (now, now + within_min)):
        distance = haversine_km(lat, lng, row["lat"], row["lng"])
        if distance > radius_km:
            continue
        events.append(
            Event(
                event_id=row["event_id"], name=row["name"], kind=row["kind"], town=row["town"],
                status="ONGOING" if row["start_min"] <= now else "UPCOMING", starts_in_min=row["start_min"] - now,
                duration_min=row["end_min"] - row["start_min"], attendance=row["attendance"], distance_km=round(distance, 2),
                serving_towers=[n for n, _ in serving_towers(conn, row["lat"], row["lng"], SERVING_TOWERS)],
            )
        )
    events = events[:MAX_EVENTS]
    data = EventList(center=Centre(lat=lat, lng=lng), radius_km=radius_km, within_min=within_min, events=events, returned=len(events))
    return wrap(conn, source=SOURCE, tool="events_list_upcoming", data=data, ref=f"{lat},{lng},{radius_km}km+{within_min}min")


def _forecast(conn: sqlite3.Connection, row: sqlite3.Row, now: int) -> Forecast:
    uplift = uplift_by_tower(conn, row)
    distances = dict(serving_towers(conn, row["lat"], row["lng"], SERVING_TOWERS))
    towers: list[TowerForecast] = []
    for name in sorted(uplift, key=lambda n: distances[n]):
        base = baseline_prb(conn, name)
        predicted = min(100.0, round(base + uplift[name], 1))
        subs = conn.execute("SELECT COALESCE(subscribers_est, 0) FROM tower_subscribers WHERE enodeb_name = ?", (name,)).fetchone()
        towers.append(
            TowerForecast(
                enodeb_name=name, distance_km=distances[name], baseline_prb=base, uplift_prb=round(uplift[name], 2),
                predicted_prb=predicted, risk=risk_for(predicted), subscribers_est=int(subs[0]) if subs else 0,
            )
        )
    overall = max((t.risk for t in towers), key=lambda r: RISK_ORDER[r])
    return Forecast(
        event_id=row["event_id"], name=row["name"], kind=row["kind"], attendance=row["attendance"], starts_in_min=row["start_min"] - now,
        peak_in_min=(row["start_min"] + row["end_min"]) // 2 - now, towers=towers, overall_risk=overall,
        subscribers_affected=sum(t.subscribers_est for t in towers),
    )


def forecast_load(conn: sqlite3.Connection, event_id: str) -> Envelope[Forecast]:
    """The load a crowd will put on the towers around the venue at its peak, and the overload risk."""
    row = _event(conn, event_id)
    return wrap(conn, source=SOURCE, tool="events_forecast_load", data=_forecast(conn, row, clock.now_min(conn)), ref=event_id)


def capacity_plan(conn: sqlite3.Connection, event_id: str) -> Envelope[Plan]:
    """Recommended preparations as data: what to do, on which towers, and which tool an agent would call next."""
    row = _event(conn, event_id)
    now = clock.now_min(conn)
    forecast = _forecast(conn, row, now)
    busy = [t for t in forecast.towers if t.risk != "LOW"]
    names = [t.enodeb_name for t in forecast.towers]
    duration = row["end_min"] - row["start_min"]
    recs: list[Recommendation] = []
    for t in busy:
        recs.append(
            Recommendation(
                priority=1 if t.risk == "HIGH" else 2, towers=[t.enodeb_name],
                advice=f"Relieve {t.enodeb_name} before the crowd ({t.predicted_prb:g}% PRB predicted): simulate a downtilt first.",
                next_tool="twin_simulate_tilt", arguments={"changes": [{"enodeb_name": t.enodeb_name, "tilt_delta_deg": 3.0}]},
            )
        )
    if row["attendance"] >= BROADCAST_ATTENDANCE:
        recs.append(
            Recommendation(
                priority=2, towers=names, advice="Offer broadcast-quality uplink on demand on the serving towers, so media crews are not stuck in the crowd.",
                next_tool="exposure_quote",
                arguments={"profile_id": "BROADCAST_UPLINK", "enodeb_names": names, "duration_min": duration, "start_in_min": max(0, row["start_min"] - now)},
            )
        )
    if busy:
        recs.append(
            Recommendation(
                priority=3, towers=[t.enodeb_name for t in busy], advice="Warn customers around the venue that data may be slow during the event.",
                next_tool="care_draft_notice", arguments={"enodeb_names": [t.enodeb_name for t in busy], "kind": "DEGRADED", "language": "en"},
            )
        )
        recs.append(
            Recommendation(
                priority=3, towers=[t.enodeb_name for t in busy], advice="Keep these towers out of the night-time sleep list before the event.",
                next_tool="energy_find_savings", arguments={"lat": row["lat"], "lng": row["lng"], "radius_km": 10.0},
            )
        )
    recs.sort(key=lambda r: r.priority)
    data = Plan(event_id=event_id, name=row["name"], overall_risk=forecast.overall_risk, recommendations=recs)
    warnings = [] if busy else ["The predicted load stays low on every serving tower: no preparation is needed."]
    return wrap(conn, source=SOURCE, tool="events_capacity_plan", data=data, ref=event_id, warnings=warnings)
