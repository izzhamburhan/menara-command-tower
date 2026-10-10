"""user-mcp tool logic. Read-only. Subscribers are identified only by msisdn_hash; location is cell-level."""

from __future__ import annotations

import sqlite3

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.ids import parse_msisdn_hash

from user_mcp.models import (
    ExperienceLabel,
    ExperiencePoint,
    ExperienceSummary,
    ExperienceWindow,
    ServingCell,
)

SOURCE = "user-mcp"
MAX_WINDOW_MIN = 1440
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
    data = ServingCell(
        msisdn_hash=sub["msisdn_hash"],
        serving_cell=sub["serving_cell"],
        enodeb_name=sub["enodeb_name"],
        attached=attached,
        detached_since=None if attached or state is None else clock.iso_at(conn, state["t_min"]),
        cell_lat=sub["cell_lat"],
        cell_lng=sub["cell_lng"],
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
