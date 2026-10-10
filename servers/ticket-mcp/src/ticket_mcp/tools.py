"""ticket-mcp tool logic. Owns the ticket_note table; every other table is read-only."""

from __future__ import annotations

import sqlite3
from collections import Counter

from menara_core import clock
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km
from menara_core.ids import parse_ticket_id

from ticket_mcp.models import (
    Centroid,
    ClusterTicket,
    LocationCount,
    Note,
    NoteAdded,
    Resolution,
    TicketCluster,
    TicketDetail,
)

SOURCE = "ticket-mcp"
OWNED_TABLES = frozenset({"ticket_note", "ticket_resolution"})
MAX_NOTE_CHARS = 1000
MAX_LIMIT = 500
MAX_RESOLVE = 200


def _visible_ticket(conn: sqlite3.Connection, ticket_id: str) -> sqlite3.Row:
    """A ticket that is not yet raised at the current scenario time does not exist for callers."""
    tid = parse_ticket_id(ticket_id)
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM ticket WHERE ticket_id = ? AND created_min <= ?", (tid, clock.now_min(conn))
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Ticket {tid} not found at the current scenario time")
    return row


def _resolved_row(conn: sqlite3.Connection, ticket_id: str) -> sqlite3.Row | None:
    row: sqlite3.Row | None = conn.execute(
        "SELECT * FROM ticket_resolution WHERE ticket_id = ? AND resolved_min <= ?", (ticket_id, clock.now_min(conn))
    ).fetchone()
    return row


def _effective_status(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    return "RESOLVED" if _resolved_row(conn, row["ticket_id"]) else str(row["status"])


def _note(row: sqlite3.Row) -> Note:
    return Note(note_id=row["note_id"], at=row["at"], author=row["author"], text=row["text"])


def get_ticket(conn: sqlite3.Connection, ticket_id: str) -> Envelope[TicketDetail]:
    row = _visible_ticket(conn, ticket_id)
    notes = [
        _note(n)
        for n in conn.execute("SELECT * FROM ticket_note WHERE ticket_id = ? ORDER BY note_id", (row["ticket_id"],))
    ]
    detail = TicketDetail(
        ticket_id=row["ticket_id"],
        created_at=clock.iso_at(conn, row["created_min"]),
        service=row["service"],
        category=row["category"],
        status=_effective_status(conn, row),
        location_text=row["location_text"],
        lat=row["lat"],
        lng=row["lng"],
        customer_ref=row["customer_ref"],
        summary=row["summary"],
        language=row["language"],
        resolved_at=(resolved["resolved_at"] if (resolved := _resolved_row(conn, row["ticket_id"])) else None),
        notes=notes,
    )
    return wrap(conn, source=SOURCE, tool="ticket_get_ticket", data=detail, ref=row["ticket_id"])


def cluster_by_location(
    conn: sqlite3.Connection,
    ticket_id: str,
    radius_km: float = 15.0,
    window_min: int = 60,
    limit: int = 100,
) -> Envelope[TicketCluster]:
    """Tickets raised within radius_km and +/- window_min of the anchor ticket, as seen at 'now'."""
    anchor = _visible_ticket(conn, ticket_id)
    if not 0.1 <= radius_km <= 100:
        raise InvalidInputError("radius_km must be between 0.1 and 100")
    if not 1 <= window_min <= 1440:
        raise InvalidInputError("window_min must be between 1 and 1440")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    if anchor["lat"] is None or anchor["lng"] is None:
        raise InvalidInputError(f"Ticket {anchor['ticket_id']} has no geocoded location to cluster around")

    min_lat, min_lng, max_lat, max_lng = bbox_around(anchor["lat"], anchor["lng"], radius_km)
    candidates = conn.execute(
        "SELECT * FROM ticket WHERE created_min BETWEEN ? AND ? AND created_min <= ? "
        "AND lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? ORDER BY created_min, ticket_id",
        (
            anchor["created_min"] - window_min,
            anchor["created_min"] + window_min,
            clock.now_min(conn),
            min_lat,
            max_lat,
            min_lng,
            max_lng,
        ),
    ).fetchall()
    members: list[tuple[float, sqlite3.Row]] = []
    for row in candidates:
        distance = haversine_km(anchor["lat"], anchor["lng"], row["lat"], row["lng"])
        if distance <= radius_km:
            members.append((distance, row))

    times = [row["created_min"] for _, row in members]
    centroid = (
        Centroid(
            lat=round(sum(r["lat"] for _, r in members) / len(members), 5),
            lng=round(sum(r["lng"] for _, r in members) / len(members), 5),
        )
        if members
        else None
    )
    shown = [
        ClusterTicket(
            ticket_id=row["ticket_id"],
            created_at=clock.iso_at(conn, row["created_min"]),
            category=row["category"],
            status=_effective_status(conn, row),
            location_text=row["location_text"],
            lat=row["lat"],
            lng=row["lng"],
            distance_km=round(distance, 2),
        )
        for distance, row in members[:limit]
    ]
    cluster = TicketCluster(
        anchor_ticket=anchor["ticket_id"],
        radius_km=radius_km,
        window_min=window_min,
        count=len(members),
        span_min=(max(times) - min(times)) if times else 0,
        centroid=centroid,
        top_locations=[
            LocationCount(location_text=name, count=count)
            for name, count in Counter(r["location_text"] for _, r in members).most_common(5)
        ],
        tickets=shown,
        returned=len(shown),
        truncated=len(members) > limit,
    )
    warnings = [f"Showing {limit} of {len(members)} tickets; count is the full total"] if cluster.truncated else []
    return wrap(
        conn, source=SOURCE, tool="ticket_cluster_by_location", data=cluster, ref=anchor["ticket_id"], warnings=warnings
    )


def add_note(
    conn: sqlite3.Connection, ticket_id: str, text: str, author: str = "agent"
) -> Envelope[NoteAdded]:
    """Append a note. Needs a connection that owns ticket_note."""
    row = _visible_ticket(conn, ticket_id)
    body, who = text.strip(), author.strip()
    if not body:
        raise InvalidInputError("Note text must not be empty")
    if len(body) > MAX_NOTE_CHARS:
        raise InvalidInputError(f"Note text must be at most {MAX_NOTE_CHARS} characters")
    if not who or len(who) > 60:
        raise InvalidInputError("author must be 1-60 characters")
    stamp = clock.as_of(conn)
    cursor = conn.execute(
        "INSERT INTO ticket_note (ticket_id, at, author, text) VALUES (?, ?, ?, ?)",
        (row["ticket_id"], stamp, who, body),
    )
    conn.commit()
    note = Note(note_id=int(cursor.lastrowid or 0), at=stamp, author=who, text=body)
    return wrap(
        conn,
        source=SOURCE,
        tool="ticket_add_note",
        data=NoteAdded(ticket_id=row["ticket_id"], note=note),
        ref=row["ticket_id"],
    )


def resolve(
    conn: sqlite3.Connection, ticket_ids: list[str], note: str, resolved_by: str = "agent"
) -> Envelope[Resolution]:
    """Close tickets (for example the whole cluster of an incident) and leave a note on each."""
    if not ticket_ids:
        raise InvalidInputError("ticket_ids must not be empty")
    ids = list(dict.fromkeys(parse_ticket_id(t) for t in ticket_ids))
    if len(ids) > MAX_RESOLVE:
        raise InvalidInputError(f"at most {MAX_RESOLVE} tickets per call")
    body, who = note.strip(), resolved_by.strip()
    if not body or len(body) > MAX_NOTE_CHARS:
        raise InvalidInputError(f"note must be 1-{MAX_NOTE_CHARS} characters")
    if not who or len(who) > 60:
        raise InvalidInputError("resolved_by must be 1-60 characters")
    rows = [_visible_ticket(conn, tid) for tid in ids]
    now, stamp = clock.now_min(conn), clock.as_of(conn)
    done: list[str] = []
    skipped: list[str] = []
    for row in rows:
        if _effective_status(conn, row) == "RESOLVED":
            skipped.append(row["ticket_id"])
            continue
        conn.execute(
            "INSERT OR REPLACE INTO ticket_resolution VALUES (?, ?, ?, ?, ?)", (row["ticket_id"], now, stamp, who, body)
        )
        conn.execute(
            "INSERT INTO ticket_note (ticket_id, at, author, text) VALUES (?, ?, ?, ?)",
            (row["ticket_id"], stamp, who, f"Resolved: {body}"),
        )
        done.append(row["ticket_id"])
    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="ticket_resolve",
        data=Resolution(resolved=done, already_resolved=skipped, count=len(done), resolved_by=who),
        ref=ids[0] if len(ids) == 1 else None,
    )
