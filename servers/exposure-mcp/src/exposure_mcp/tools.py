"""exposure-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Owns `qod_booking` (bookings that were approved and made). Reads, read-only: `qod_profile`, `crowd_event`, `tower`,
`tower_state`, `tower_kpi`, `tower_subscribers`, and the RAN effects through `menara_core.kpi_overlay`. Products, prices
and capacity are invented.

Model: a tower can be sold a profile when it is up and its spare capacity (100 - PRB now - the crowd of an event in the
window - the headroom already reserved by overlapping bookings) covers the profile's headroom plus a 5-point safety
margin. Booking sells a service, so it needs a signed policy token for `exposure_book_qod` (policy always asks a human).
"""

from __future__ import annotations

import sqlite3

from menara_core import clock, kpi_overlay, settings
from menara_core.crowd import uplift_by_tower
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.ids import parse_enodeb, target_key
from menara_core.tokens import verify_token

from exposure_mcp.models import Booking, Profile, ProfileList, Quote, TowerQuote

SOURCE = "exposure-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"qod_booking"})
ACTION = "exposure_book_qod"
MIN_SPARE_PRB = 5.0
MIN_DURATION_MIN, MAX_DURATION_MIN = 15, 720
MAX_START_IN_MIN = 4320
MAX_TOWERS = 20
MIN_CUSTOMER, MAX_CUSTOMER = 3, 60


def _profile(conn: sqlite3.Connection, profile_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM qod_profile WHERE profile_id = ?", (profile_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"Profile {profile_id} not found")
    return row  # type: ignore[no-any-return]


def list_profiles(conn: sqlite3.Connection) -> Envelope[ProfileList]:
    """The catalogue of quality-on-demand profiles."""
    rows = conn.execute("SELECT * FROM qod_profile ORDER BY profile_id").fetchall()
    data = ProfileList(profiles=[Profile(**dict(r)) for r in rows])
    return wrap(conn, source=SOURCE, tool="exposure_list_profiles", data=data)


def _towers(conn: sqlite3.Connection, names: list[str]) -> list[str]:
    if not 1 <= len(names) <= MAX_TOWERS:
        raise InvalidInputError(f"Give between 1 and {MAX_TOWERS} towers")
    parsed = list(dict.fromkeys(parse_enodeb(n) for n in names))
    for name in parsed:
        if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
            raise NotFoundError(f"Tower {name} not found")
    return parsed


def _check_window(duration_min: int, start_in_min: int) -> None:
    if not MIN_DURATION_MIN <= duration_min <= MAX_DURATION_MIN:
        raise InvalidInputError(f"duration_min must be between {MIN_DURATION_MIN} and {MAX_DURATION_MIN}")
    if not 0 <= start_in_min <= MAX_START_IN_MIN:
        raise InvalidInputError(f"start_in_min must be between 0 and {MAX_START_IN_MIN}")


def _current_prb(conn: sqlite3.Connection, name: str, now: int) -> float:
    row = conn.execute(
        "SELECT prb_util, drop_rate, throughput_mbps FROM tower_kpi WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (name, now)
    ).fetchone()
    if row is None:
        return 0.0
    prb, _, _ = kpi_overlay.adjust(conn, name, now, row["prb_util"], row["drop_rate"], row["throughput_mbps"])
    return float(prb)


def _status(conn: sqlite3.Connection, name: str, now: int) -> str:
    row = conn.execute(
        "SELECT status FROM tower_state WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (name, now)
    ).fetchone()
    return str(row["status"]) if row else "UP"


def _event_uplift(conn: sqlite3.Connection, start: int, end: int) -> dict[str, float]:
    total: dict[str, float] = {}
    for event in conn.execute("SELECT * FROM crowd_event WHERE start_min < ? AND end_min > ?", (end, start)):
        for name, points in uplift_by_tower(conn, event).items():
            total[name] = total.get(name, 0.0) + points
    return total


def _reserved(conn: sqlite3.Connection, name: str, start: int, end: int) -> float:
    total = 0.0
    for row in conn.execute(
        "SELECT b.towers, p.headroom_prb FROM qod_booking b JOIN qod_profile p ON p.profile_id = b.profile_id WHERE b.from_min < ? AND b.to_min > ?",
        (end, start),
    ):
        if name in row["towers"].split(","):
            total += row["headroom_prb"]
    return total


def _quote(conn: sqlite3.Connection, profile: sqlite3.Row, names: list[str], duration_min: int, start_in_min: int) -> Quote:
    now = clock.now_min(conn)
    start, end = now + start_in_min, now + start_in_min + duration_min
    uplift = _event_uplift(conn, start, end)
    need = profile["headroom_prb"] + MIN_SPARE_PRB
    towers: list[TowerQuote] = []
    for name in names:
        status = _status(conn, name, now)
        current = _current_prb(conn, name, now)
        extra = round(uplift.get(name, 0.0), 1)
        reserved = _reserved(conn, name, start, end)
        available = round(100.0 - current - extra - reserved, 1)
        reason = ""
        if status != "UP":
            reason = f"the tower is not up ({status.lower()})"
        elif available < need:
            reason = f"only {max(available, 0.0):g}% spare capacity; {need:g}% is needed"
        towers.append(
            TowerQuote(
                enodeb_name=name, status=status, current_prb=round(current, 1), event_uplift_prb=extra, reserved_prb=reserved,
                headroom_available_prb=available, feasible=reason == "", reason=reason,
            )
        )
    feasible = [t.enodeb_name for t in towers if t.feasible]
    price = round(duration_min / 60.0 * profile["price_rm_per_hour_per_tower"] * len(feasible), 2)
    return Quote(
        profile_id=profile["profile_id"], duration_min=duration_min, start_in_min=start_in_min, towers=towers, feasible_towers=feasible,
        all_feasible=len(feasible) == len(towers), price_rm=price, reserved_prb_per_tower=profile["headroom_prb"],
    )


def quote(conn: sqlite3.Connection, profile_id: str, enodeb_names: list[str], duration_min: int, start_in_min: int = 0) -> Envelope[Quote]:
    """Can these towers be sold this profile for a window, and for how much? Nothing is written."""
    _check_window(duration_min, start_in_min)
    profile = _profile(conn, profile_id)
    names = _towers(conn, enodeb_names)
    data = _quote(conn, profile, names, duration_min, start_in_min)
    warnings = [] if data.all_feasible else [f"{len(names) - len(data.feasible_towers)} of {len(names)} towers cannot be sold this profile for that window."]
    return wrap(conn, source=SOURCE, tool="exposure_quote", data=data, ref=f"{profile_id}:{target_key(names)}", warnings=warnings)


def book(
    conn: sqlite3.Connection,
    profile_id: str,
    enodeb_names: list[str],
    duration_min: int,
    customer: str,
    policy_token: str,
    reason: str = "",
    start_in_min: int = 0,
) -> Envelope[Booking]:
    """Book a profile on these towers for a customer. Needs a policy token for action exposure_book_qod on exactly these towers."""
    _check_window(duration_min, start_in_min)
    name_text = customer.strip()
    if not MIN_CUSTOMER <= len(name_text) <= MAX_CUSTOMER:
        raise InvalidInputError(f"customer must be {MIN_CUSTOMER} to {MAX_CUSTOMER} characters (a fictional name)")
    profile = _profile(conn, profile_id)
    names = _towers(conn, enodeb_names)
    grant = verify_token(settings.signing_key(), policy_token, action=ACTION, target=target_key(names))
    offer = _quote(conn, profile, names, duration_min, start_in_min)
    if not offer.all_feasible:
        why = "; ".join(f"{t.enodeb_name}: {t.reason}" for t in offer.towers if not t.feasible)
        raise InvalidInputError(f"Cannot book: {why}")
    now = clock.now_min(conn)
    cursor = conn.execute(
        "INSERT INTO qod_booking (profile_id, towers, customer, from_min, to_min, price_rm, approved_by, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (profile_id, target_key(names), name_text, now + start_in_min, now + start_in_min + duration_min, offer.price_rm, grant.approved_by, reason.strip()[:300]),
    )
    booking_id = f"BKG-{int(cursor.lastrowid or 0):04d}"
    conn.execute("UPDATE qod_booking SET booking_id = ? WHERE seq = ?", (booking_id, cursor.lastrowid))
    conn.commit()
    data = Booking(
        booking_id=booking_id, profile_id=profile_id, towers=sorted(set(names)), customer=name_text, from_min=now + start_in_min,
        to_min=now + start_in_min + duration_min, price_rm=offer.price_rm, approved_by=grant.approved_by,
    )
    return wrap(conn, source=SOURCE, tool="exposure_book", data=data, ref=booking_id)
