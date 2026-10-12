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
    McmcEligibility,
    Note,
    NoteAdded,
    NttDetail,
    NttLinkResult,
    NttList,
    NttResolution,
    NttSummary,
    NttUnlinkResult,
    Resolution,
    TicketCluster,
    TicketDetail,
)

SOURCE = "ticket-mcp"
OWNED_TABLES = frozenset({"ticket_note", "ticket_resolution", "ntt", "ntt_ctt_link", "ntt_note"})
MAX_NOTE_CHARS = 1000
MAX_LIMIT = 500
MAX_RESOLVE = 200
MAX_NTT_SUMMARY_CHARS = 500
VALID_FAULT_TYPES = frozenset({"POWER", "FLOOD", "FIBER", "RAN", "HARDWARE", "OTHER"})
VALID_SEVERITIES = frozenset({"CRITICAL", "MAJOR", "MINOR"})
VALID_NTT_STATUSES = frozenset({"IN_PROGRESS", "RESOLVED", "CLOSED", "CANCELLED"})

# Invented demo rules for a simulated regulator notice (nothing is sent; not a statement of any real regulation).
MCMC_OUTAGE_THRESHOLD_MIN = 120
MCMC_COMPREHENSIVE_REPORT_DAYS = 3
SEVERITY_RANK = {"MINOR": 0, "MAJOR": 1, "CRITICAL": 2}
MCMC_SERVICE_IMPACTING_SEVERITIES = frozenset({"CRITICAL", "MAJOR"})
MCMC_SERVICE_IMPACTING_FAULTS = frozenset({"POWER", "FLOOD", "FIBER", "RAN", "HARDWARE"})


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


def _format_ntt_id(seq: int) -> str:
    return f"NTT-{seq:04d}"


def _get_ntt_row(conn: sqlite3.Connection, ntt_id: str) -> sqlite3.Row:
    clean_id = ntt_id.strip().upper()
    row: sqlite3.Row | None = conn.execute("SELECT * FROM ntt WHERE ntt_id = ?", (clean_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"NTT {clean_id} not found")
    return row


def _linked_ctt_ids(conn: sqlite3.Connection, ntt_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT ticket_id FROM ntt_ctt_link WHERE ntt_id = ? ORDER BY linked_min, ticket_id",
        (ntt_id,),
    ).fetchall()
    return [r["ticket_id"] for r in rows]


def _ntt_notes(conn: sqlite3.Connection, ntt_id: str) -> list[Note]:
    rows = conn.execute("SELECT * FROM ntt_note WHERE ntt_id = ? ORDER BY note_id", (ntt_id,)).fetchall()
    return [_note(r) for r in rows]


def _build_ntt_detail(conn: sqlite3.Connection, row: sqlite3.Row) -> NttDetail:
    linked = _linked_ctt_ids(conn, row["ntt_id"])
    notes = _ntt_notes(conn, row["ntt_id"])
    return NttDetail(
        ntt_id=row["ntt_id"],
        created_at=row["created_at"],
        network_element_id=row["network_element_id"],
        fault_type=row["fault_type"],
        severity=row["severity"],
        status=row["status"],
        summary=row["summary"],
        ctt_count=len(linked),
        linked_ctt_ids=linked,
        notes=notes,
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
        resolution_note=row["resolution_note"],
        mcmc_closure_sent=bool(row["mcmc_closure_sent"]),
        mcmc_comprehensive_required=bool(row["mcmc_comprehensive_required"]),
    )


def _check_element(conn: sqlite3.Connection, ne_id: str) -> None:
    """The element must be a tower (enodeb_name) or a power feeder (feeder_id). Read-only look at those base tables."""
    name = ne_id.removeprefix("SITE-")
    if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone():
        return
    if conn.execute("SELECT 1 FROM grid_feeder WHERE feeder_id = ?", (ne_id,)).fetchone():
        return
    raise NotFoundError(f"Network element {ne_id} not found (use a tower enodeb_name or a feeder id)")


def create_ntt(
    conn: sqlite3.Connection,
    network_element_id: str,
    fault_type: str,
    severity: str,
    summary: str,
    ctt_ticket_ids: list[str] | None = None,
) -> Envelope[NttDetail]:
    ne_id = network_element_id.strip().upper()
    if not ne_id or len(ne_id) > 60:
        raise InvalidInputError("network_element_id must be 1-60 characters")
    ft = fault_type.strip().upper()
    if ft not in VALID_FAULT_TYPES:
        raise InvalidInputError(f"fault_type must be one of {sorted(VALID_FAULT_TYPES)}")
    sev = severity.strip().upper()
    if sev not in VALID_SEVERITIES:
        raise InvalidInputError(f"severity must be one of {sorted(VALID_SEVERITIES)}")
    summ = summary.strip()
    if len(summ) < 5 or len(summ) > MAX_NTT_SUMMARY_CHARS:
        raise InvalidInputError(f"summary must be 5-{MAX_NTT_SUMMARY_CHARS} characters")

    _check_element(conn, ne_id)
    ctts_to_link: list[str] = []
    if ctt_ticket_ids:
        for tid in ctt_ticket_ids:
            row = _visible_ticket(conn, tid)
            ctts_to_link.append(row["ticket_id"])

    now, stamp = clock.now_min(conn), clock.as_of(conn)

    existing = conn.execute(
        "SELECT * FROM ntt WHERE network_element_id = ? AND status = 'IN_PROGRESS' ORDER BY seq DESC LIMIT 1",
        (ne_id,),
    ).fetchone()

    warnings: list[str] = []
    if existing is not None:
        ntt_id = existing["ntt_id"]
        warnings.append(f"Existing active NTT {ntt_id} for {ne_id} was reused.")
        if ft != existing["fault_type"]:
            warnings.append(f"fault_type {ft} was ignored: the existing NTT says {existing['fault_type']}.")
        if SEVERITY_RANK[sev] > SEVERITY_RANK[existing["severity"]]:
            conn.execute("UPDATE ntt SET severity = ? WHERE ntt_id = ?", (sev, ntt_id))
            conn.execute(
                "INSERT INTO ntt_note (ntt_id, at, author, text) VALUES (?, ?, ?, ?)",
                (ntt_id, stamp, "system", f"Severity raised from {existing['severity']} to {sev}: {summ}"),
            )
            warnings.append(f"Severity raised from {existing['severity']} to {sev}.")
        elif sev != existing["severity"]:
            warnings.append(f"severity {sev} was ignored: the existing NTT is {existing['severity']}.")
        for tid in ctts_to_link:
            conn.execute(
                "INSERT OR IGNORE INTO ntt_ctt_link VALUES (?, ?, ?, ?)",
                (ntt_id, tid, now, stamp),
            )
        conn.commit()
        detail = _build_ntt_detail(conn, _get_ntt_row(conn, ntt_id))
        return wrap(conn, source=SOURCE, tool="ticket_create_ntt", data=detail, ref=ntt_id, warnings=warnings)

    cursor = conn.execute(
        "INSERT INTO ntt (created_min, created_at, network_element_id, fault_type, severity, status, summary) "
        "VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?)",
        (now, stamp, ne_id, ft, sev, summ),
    )
    seq = int(cursor.lastrowid or 0)
    ntt_id = _format_ntt_id(seq)
    conn.execute("UPDATE ntt SET ntt_id = ? WHERE seq = ?", (ntt_id, seq))

    for tid in ctts_to_link:
        conn.execute(
            "INSERT OR IGNORE INTO ntt_ctt_link VALUES (?, ?, ?, ?)",
            (ntt_id, tid, now, stamp),
        )
    conn.commit()

    created_row = conn.execute("SELECT * FROM ntt WHERE seq = ?", (seq,)).fetchone()
    detail = _build_ntt_detail(conn, created_row)
    return wrap(conn, source=SOURCE, tool="ticket_create_ntt", data=detail, ref=ntt_id)


def get_ntt(conn: sqlite3.Connection, ntt_id: str) -> Envelope[NttDetail]:
    row = _get_ntt_row(conn, ntt_id)
    detail = _build_ntt_detail(conn, row)
    return wrap(conn, source=SOURCE, tool="ticket_get_ntt", data=detail, ref=row["ntt_id"])


def list_ntts(
    conn: sqlite3.Connection,
    status: str | None = None,
    network_element_id: str | None = None,
    limit: int = 50,
) -> Envelope[NttList]:
    if not 1 <= limit <= 200:
        raise InvalidInputError("limit must be between 1 and 200")
    stat = status.strip().upper() if status else None
    if stat and stat not in VALID_NTT_STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(VALID_NTT_STATUSES)}")
    ne_id = network_element_id.strip().upper() if network_element_id else None

    clauses: list[str] = []
    params: list[object] = []
    if stat:
        clauses.append("status = ?")
        params.append(stat)
    if ne_id:
        clauses.append("network_element_id = ?")
        params.append(ne_id)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM ntt {where} ORDER BY seq DESC", params).fetchall()

    items: list[NttSummary] = []
    for r in rows[:limit]:
        ctt_count = conn.execute("SELECT COUNT(*) FROM ntt_ctt_link WHERE ntt_id = ?", (r["ntt_id"],)).fetchone()[0]
        items.append(
            NttSummary(
                ntt_id=r["ntt_id"],
                created_at=r["created_at"],
                network_element_id=r["network_element_id"],
                fault_type=r["fault_type"],
                severity=r["severity"],
                status=r["status"],
                summary=r["summary"],
                ctt_count=int(ctt_count),
            )
        )
    result = NttList(ntts=items, total=len(rows), truncated=len(rows) > limit)
    warnings = [f"Showing {limit} of {len(rows)} NTTs"] if result.truncated else []
    return wrap(conn, source=SOURCE, tool="ticket_list_ntts", data=result, warnings=warnings)


def link_ctts(
    conn: sqlite3.Connection,
    ntt_id: str,
    ctt_ticket_ids: list[str],
) -> Envelope[NttLinkResult]:
    row = _get_ntt_row(conn, ntt_id)
    if not ctt_ticket_ids:
        raise InvalidInputError("ctt_ticket_ids must not be empty")
    if len(ctt_ticket_ids) > 200:
        raise InvalidInputError("At most 200 CTTs per call")

    tids = [parse_ticket_id(t) for t in ctt_ticket_ids]
    now, stamp = clock.now_min(conn), clock.as_of(conn)

    linked: list[str] = []
    already: list[str] = []
    for tid in tids:
        _visible_ticket(conn, tid)
        exists = conn.execute(
            "SELECT 1 FROM ntt_ctt_link WHERE ntt_id = ? AND ticket_id = ?",
            (row["ntt_id"], tid),
        ).fetchone()
        if exists:
            already.append(tid)
        else:
            conn.execute("INSERT INTO ntt_ctt_link VALUES (?, ?, ?, ?)", (row["ntt_id"], tid, now, stamp))
            linked.append(tid)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM ntt_ctt_link WHERE ntt_id = ?", (row["ntt_id"],)).fetchone()[0]
    return wrap(
        conn,
        source=SOURCE,
        tool="ticket_link_ctts",
        data=NttLinkResult(ntt_id=row["ntt_id"], linked=linked, already_linked=already, ctt_count=int(total)),
        ref=row["ntt_id"],
    )


def unlink_ctt(
    conn: sqlite3.Connection,
    ntt_id: str,
    ctt_ticket_id: str,
) -> Envelope[NttUnlinkResult]:
    row = _get_ntt_row(conn, ntt_id)
    tid = parse_ticket_id(ctt_ticket_id)
    deleted = conn.execute(
        "DELETE FROM ntt_ctt_link WHERE ntt_id = ? AND ticket_id = ?",
        (row["ntt_id"], tid),
    ).rowcount
    if deleted == 0:
        raise NotFoundError(f"CTT {tid} is not linked to NTT {row['ntt_id']}")
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM ntt_ctt_link WHERE ntt_id = ?", (row["ntt_id"],)).fetchone()[0]
    return wrap(
        conn,
        source=SOURCE,
        tool="ticket_unlink_ctt",
        data=NttUnlinkResult(ntt_id=row["ntt_id"], unlinked_ticket_id=tid, ctt_count=int(total)),
        ref=row["ntt_id"],
    )


def _evaluate_mcmc_eligibility(conn: sqlite3.Connection, row: sqlite3.Row) -> McmcEligibility:
    created_min = int(row["created_min"])
    resolved_min = int(row["resolved_min"]) if row["resolved_min"] is not None else None
    current_min = clock.now_min(conn)

    duration = (resolved_min - created_min) if resolved_min is not None else (current_min - created_min)
    duration = max(0, duration)

    reasons: list[str] = []
    sev = str(row["severity"])
    if sev not in MCMC_SERVICE_IMPACTING_SEVERITIES:
        reasons.append(f"Severity is {sev} (must be CRITICAL or MAJOR)")

    ft = str(row["fault_type"])
    if ft not in MCMC_SERVICE_IMPACTING_FAULTS:
        reasons.append(f"Fault type {ft} is non-service impacting")

    if duration < MCMC_OUTAGE_THRESHOLD_MIN:
        reasons.append(
            f"Outage duration is {duration} min (demo threshold is {MCMC_OUTAGE_THRESHOLD_MIN} min)"
        )

    can_send = len(reasons) == 0
    display_msg = "ELIGIBLE (SIMULATED, NOTHING SENT)" if can_send else "NOT ELIGIBLE"

    is_closure_sent = bool(row["mcmc_closure_sent"])
    is_comp_req = bool(row["mcmc_comprehensive_required"])
    comp_aging_days = MCMC_COMPREHENSIVE_REPORT_DAYS if (can_send or is_comp_req) else None

    return McmcEligibility(
        can_send=can_send,
        can_send_display_message=display_msg,
        outage_duration_min=duration,
        is_mcmc_closure_sent=is_closure_sent,
        is_mcmc_comprehensive_required=is_comp_req,
        comprehensive_report_aging_days=comp_aging_days,
        reasons=reasons,
    )


def check_mcmc(conn: sqlite3.Connection, ntt_id: str) -> Envelope[McmcEligibility]:
    row = _get_ntt_row(conn, ntt_id)
    eligibility = _evaluate_mcmc_eligibility(conn, row)
    return wrap(conn, source=SOURCE, tool="ticket_check_mcmc", data=eligibility, ref=row["ntt_id"])


def resolve_ntt(
    conn: sqlite3.Connection,
    ntt_id: str,
    resolution_note: str,
    resolved_by: str = "agent",
) -> Envelope[NttResolution]:
    row = _get_ntt_row(conn, ntt_id)
    if row["status"] in {"RESOLVED", "CLOSED", "CANCELLED"}:
        raise InvalidInputError(f"NTT {row['ntt_id']} is already {row['status']}")

    note_text, who = resolution_note.strip(), resolved_by.strip()
    if not note_text or len(note_text) > MAX_NOTE_CHARS:
        raise InvalidInputError(f"resolution_note must be 1-{MAX_NOTE_CHARS} characters")
    if not who or len(who) > 60:
        raise InvalidInputError("resolved_by must be 1-60 characters")

    now, stamp = clock.now_min(conn), clock.as_of(conn)

    conn.execute(
        "UPDATE ntt SET status = 'RESOLVED', resolved_min = ?, resolved_at = ?, resolved_by = ?, resolution_note = ? WHERE ntt_id = ?",
        (now, stamp, who, note_text, row["ntt_id"]),
    )
    conn.execute(
        "INSERT INTO ntt_note (ntt_id, at, author, text) VALUES (?, ?, ?, ?)",
        (row["ntt_id"], stamp, who, f"Resolved: {note_text}"),
    )

    updated_row = _get_ntt_row(conn, ntt_id)
    mcmc = _evaluate_mcmc_eligibility(conn, updated_row)

    if mcmc.can_send:
        conn.execute(
            "UPDATE ntt SET mcmc_closure_sent = 1, mcmc_comprehensive_required = 1 WHERE ntt_id = ?",
            (row["ntt_id"],),
        )
        conn.execute(
            "INSERT INTO ntt_note (ntt_id, at, author, text) VALUES (?, ?, ?, ?)",
            (
                row["ntt_id"],
                stamp,
                "system",
                f"Simulated MCMC closure notice recorded (outage {mcmc.outage_duration_min} min; nothing was sent). "
                f"Simulated comprehensive report due in {MCMC_COMPREHENSIVE_REPORT_DAYS} days.",
            ),
        )
        mcmc.is_mcmc_closure_sent = True
        mcmc.is_mcmc_comprehensive_required = True
        mcmc.comprehensive_report_aging_days = MCMC_COMPREHENSIVE_REPORT_DAYS

    linked = _linked_ctt_ids(conn, row["ntt_id"])
    resolved_ctts: list[str] = []
    for tid in linked:
        ctt_row = conn.execute("SELECT * FROM ticket WHERE ticket_id = ?", (tid,)).fetchone()
        if ctt_row and _effective_status(conn, ctt_row) != "RESOLVED":
            conn.execute(
                "INSERT OR REPLACE INTO ticket_resolution VALUES (?, ?, ?, ?, ?)",
                (tid, now, stamp, who, f"Resolved via NTT {row['ntt_id']}: {note_text}"),
            )
            conn.execute(
                "INSERT INTO ticket_note (ticket_id, at, author, text) VALUES (?, ?, ?, ?)",
                (tid, stamp, who, f"Resolved via NTT {row['ntt_id']}: {note_text}"),
            )
            resolved_ctts.append(tid)

    conn.commit()
    return wrap(
        conn,
        source=SOURCE,
        tool="ticket_resolve_ntt",
        data=NttResolution(
            ntt_id=row["ntt_id"],
            status="RESOLVED",
            resolved_ctts=resolved_ctts,
            resolution_note=note_text,
            resolved_by=who,
            mcmc=mcmc,
        ),
        ref=row["ntt_id"],
    )
