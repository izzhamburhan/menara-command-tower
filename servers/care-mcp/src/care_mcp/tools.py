"""care-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Owns `care_notice` (notices that were approved and sent). Reads, read-only: `tower`, `tower_state`, `tower_subscribers`,
`ticket`, `ticket_resolution`, `grid_feeder_tower`, `grid_feeder_state`, `flood_extent`, `care_template`, `care_language_mix`.
Counts only: there is no recipient list, no phone number and no subscriber hash anywhere. All numbers are synthetic.

Model: after an outage, a share of the affected customers raise a ticket in the next hour (`EXTRA_TICKET_RATE` by cause);
a notice that reaches them deflects 55% of those tickets. Sending a notice is a real-world action: it needs a signed
policy token for `comms_send_notice` (policy always asks a human).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from menara_core import clock, settings
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import haversine_km
from menara_core.ids import parse_enodeb, target_key
from menara_core.tokens import verify_token

from care_mcp.models import CategoryCount, Draft, Impact, Notice, NoticeList

SOURCE = "care-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"care_notice"})
ACTION = "comms_send_notice"
MIN_RECIPIENTS = 5
SMS_COST_RM = 0.06  # synthetic
EXTRA_TICKET_RATE = {"FLOOD": 0.045, "POWER": 0.03, "CONGESTION": 0.02}
DEFLECTION = 0.55
DEDUPE_MIN = 30
NEARBY_KM = 15.0
MIN_MESSAGE, MAX_MESSAGE = 20, 480
MAX_TOWERS = 50
KINDS = ("OUTAGE", "RESTORED", "DEGRADED")
LANGUAGES = ("ms", "en", "zh", "ta")
AFFECTED = ("DOWN", "DEGRADED")

CAUSE_TEXT = {
    "FLOOD": {"en": "flooding", "ms": "banjir", "zh": "洪水", "ta": "வெள்ளம்"},
    "POWER": {"en": "a power failure", "ms": "gangguan bekalan elektrik", "zh": "停电", "ta": "மின்தடை"},
    "CONGESTION": {"en": "high demand", "ms": "permintaan tinggi", "zh": "需求高峰", "ta": "அதிக தேவை"},
    "EARLIER": {"en": "the earlier disruption", "ms": "gangguan sebelum ini", "zh": "此前的中断", "ta": "முந்தைய இடையூறு"},
}
ETA_UNKNOWN = {"en": "to be confirmed", "ms": "akan dimaklumkan", "zh": "待定", "ta": "உறுதிசெய்யப்படும்"}
CARE_LINE = {
    "ms": "halaman Bantuan dalam aplikasi (demo, bukan nombor sebenar)",
    "en": "the Help page in the app (demo, not a real number)",
    "zh": "应用内的帮助页面（演示，非真实号码）",
    "ta": "செயலியின் உதவிப் பக்கம் (டெமோ, உண்மையான எண் அல்ல)",
}


def withhold(customers: int) -> bool:
    """An audience this small is not described or messaged (the same rule as the subscriber lists)."""
    return customers < MIN_RECIPIENTS


def _towers(conn: sqlite3.Connection, names: list[str]) -> list[str]:
    if not 1 <= len(names) <= MAX_TOWERS:
        raise InvalidInputError(f"Give between 1 and {MAX_TOWERS} towers")
    parsed = list(dict.fromkeys(parse_enodeb(n) for n in names))
    for name in parsed:
        if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
            raise NotFoundError(f"Tower {name} not found")
    return parsed


def _status(conn: sqlite3.Connection, name: str, now: int) -> tuple[str, bool]:
    row = conn.execute(
        "SELECT status, mains_ok FROM tower_state WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (name, now)
    ).fetchone()
    if row is None:
        row = conn.execute("SELECT status, mains_ok FROM tower_state WHERE enodeb_name = ? ORDER BY t_min LIMIT 1", (name,)).fetchone()
    return (str(row["status"]), bool(row["mains_ok"])) if row else ("UP", True)


def _customers(conn: sqlite3.Connection, names: list[str]) -> int:
    if not names:
        return 0
    marks = ", ".join("?" for _ in names)
    return int(conn.execute(f"SELECT COALESCE(SUM(subscribers_est), 0) FROM tower_subscribers WHERE enodeb_name IN ({marks})", names).fetchone()[0])


def _affected(conn: sqlite3.Connection, names: list[str], now: int) -> list[str]:
    return [n for n in names if _status(conn, n, now)[0] in AFFECTED]


def _cause(conn: sqlite3.Connection, affected: list[str], now: int) -> str | None:
    if not affected:
        return None
    extents = conn.execute("SELECT lat, lng, radius_km FROM flood_extent WHERE from_min <= ?", (now,)).fetchall()
    for name in affected:
        t = conn.execute("SELECT lat, lng FROM tower WHERE enodeb_name = ?", (name,)).fetchone()
        if any(haversine_km(t["lat"], t["lng"], e["lat"], e["lng"]) <= e["radius_km"] for e in extents):
            return "FLOOD"
    if any(not _status(conn, n, now)[1] for n in affected):
        return "POWER"
    return "CONGESTION"


def _eta(conn: sqlite3.Connection, affected: list[str], now: int) -> str | None:
    for name in affected:
        row = conn.execute(
            "SELECT s.restoration_eta_min FROM grid_feeder_tower f JOIN grid_feeder_state s ON s.feeder_id = f.feeder_id "
            "WHERE f.enodeb_name = ? AND s.t_min <= ? ORDER BY s.t_min DESC LIMIT 1",
            (name, now),
        ).fetchone()
        if row is not None and row["restoration_eta_min"] is not None:
            return datetime.fromisoformat(clock.iso_at(conn, int(row["restoration_eta_min"]))).strftime("%H:%M")
    return None


def _tickets(conn: sqlite3.Connection, affected: list[str], now: int) -> tuple[int, list[CategoryCount]]:
    if not affected:
        return 0, []
    spots = [conn.execute("SELECT lat, lng FROM tower WHERE enodeb_name = ?", (n,)).fetchone() for n in affected]
    counts: dict[str, int] = {}
    total = 0
    for t in conn.execute(
        "SELECT category, lat, lng FROM ticket WHERE created_min <= ? AND lat IS NOT NULL AND status = 'OPEN' "
        "AND ticket_id NOT IN (SELECT ticket_id FROM ticket_resolution WHERE resolved_min <= ?)",
        (now, now),
    ):
        if any(haversine_km(s["lat"], s["lng"], t["lat"], t["lng"]) <= NEARBY_KM for s in spots):
            total += 1
            counts[t["category"]] = counts.get(t["category"], 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return total, [CategoryCount(category=c, count=n) for c, n in top]


def _language_mix(conn: sqlite3.Connection, affected: list[str]) -> dict[str, float]:
    weights: dict[str, float] = {}
    total = 0.0
    for name in affected:
        row = conn.execute(
            "SELECT t.state, COALESCE(s.subscribers_est, 0) AS n FROM tower t LEFT JOIN tower_subscribers s ON s.enodeb_name = t.enodeb_name "
            "WHERE t.enodeb_name = ?",
            (name,),
        ).fetchone()
        for m in conn.execute("SELECT language, share FROM care_language_mix WHERE state = ?", (row["state"],)):
            weights[m["language"]] = weights.get(m["language"], 0.0) + m["share"] * row["n"]
        total += row["n"]
    return {k: round(v / total, 3) for k, v in sorted(weights.items())} if total else {}


def _notified(conn: sqlite3.Connection, affected: list[str]) -> tuple[int, int]:
    """(customers already told, notices sent) for notices that reached any of these towers."""
    told = 0
    count = 0
    for row in conn.execute("SELECT towers, recipients_est FROM care_notice WHERE kind != 'RESTORED'"):
        if set(row["towers"].split(",")) & set(affected):
            told += row["recipients_est"]
            count += 1
    return told, count


def get_impact(conn: sqlite3.Connection, enodeb_names: list[str]) -> Envelope[Impact]:
    """Who is affected by an outage on these towers, and how many tickets will follow if nobody is told."""
    names = _towers(conn, enodeb_names)
    now = clock.now_min(conn)
    affected = _affected(conn, names, now)
    customers = _customers(conn, affected)
    cause = _cause(conn, affected, now)
    tickets, top = _tickets(conn, affected, now)
    silent = round(customers * EXTRA_TICKET_RATE.get(cause or "", 0.0))
    told, notices = _notified(conn, affected)
    share = min(1.0, told / customers) if customers else 0.0
    hidden = bool(affected) and withhold(customers)
    data = Impact(
        affected_towers=affected, affected_customers=customers, withheld=hidden, cause=cause, open_tickets_nearby=tickets,
        top_categories=top, predicted_extra_tickets_if_silent=silent, predicted_extra_tickets_1h=round(silent * (1 - DEFLECTION * share)),
        notified_customers=min(told, customers), notices_sent=notices, language_mix=_language_mix(conn, affected), restoration_eta=_eta(conn, affected, now),
    )
    warnings = [] if affected else ["None of these towers is down or degraded at the scenario clock, so nobody is affected."]
    if hidden:
        warnings.append(f"Fewer than {MIN_RECIPIENTS} estimated customers; the audience is too small to describe.")
    return wrap(conn, source=SOURCE, tool="care_get_impact", data=data, ref=target_key(names), warnings=warnings)


def _area(conn: sqlite3.Connection, names: list[str]) -> str:
    towns = list(dict.fromkeys(conn.execute("SELECT town FROM tower WHERE enodeb_name = ?", (n,)).fetchone()["town"] for n in names))
    return towns[0] if len(towns) == 1 else f"{towns[0]} and {len(towns) - 1} more area" + ("s" if len(towns) > 2 else "")


def _check_kind_language(kind: str, language: str) -> None:
    if kind not in KINDS:
        raise InvalidInputError(f"kind must be one of {list(KINDS)}")
    if language not in LANGUAGES:
        raise InvalidInputError(f"language must be one of {list(LANGUAGES)}")


def _audience(conn: sqlite3.Connection, names: list[str], kind: str, now: int) -> list[str]:
    return names if kind == "RESTORED" else _affected(conn, names, now)


def draft_notice(conn: sqlite3.Connection, enodeb_names: list[str], kind: str = "OUTAGE", language: str = "en") -> Envelope[Draft]:
    """A customer notice with the fields filled. Nothing is sent and nothing is written."""
    _check_kind_language(kind, language)
    names = _towers(conn, enodeb_names)
    now = clock.now_min(conn)
    audience = _audience(conn, names, kind, now)
    cause = _cause(conn, _affected(conn, names, now), now) or "EARLIER"
    eta = _eta(conn, _affected(conn, names, now), now)
    template = conn.execute("SELECT body FROM care_template WHERE kind = ? AND language = ?", (kind, language)).fetchone()["body"]
    message = template.format(
        area=_area(conn, audience or names), cause=CAUSE_TEXT[cause][language], eta=eta or ETA_UNKNOWN[language], care_line=CARE_LINE[language]
    )
    recipients = _customers(conn, audience)
    data = Draft(
        kind=kind, language=language, message=message, characters=len(message), audience_towers=audience, recipients_est=recipients,
        channel="SMS", cost_rm=round(recipients * SMS_COST_RM, 2), expected_deflection_pct=round(DEFLECTION * 100) if kind != "RESTORED" else 0,
        restoration_eta=eta,
    )
    warnings = [] if audience else ["No customers are affected on these towers, so this notice would reach nobody."]
    return wrap(conn, source=SOURCE, tool="care_draft_notice", data=data, ref=f"{kind}:{language}", warnings=warnings)


def _notice(row: sqlite3.Row) -> Notice:
    return Notice(
        notice_id=row["notice_id"], kind=row["kind"], towers=row["towers"].split(","), language=row["language"],
        recipients_est=row["recipients_est"], message=row["message"], sent_at=row["sent_at"], approved_by=row["approved_by"],
        tickets_deflected_est=row["tickets_deflected_est"],
    )


def send_notice(
    conn: sqlite3.Connection,
    enodeb_names: list[str],
    language: str,
    message: str,
    policy_token: str,
    reason: str = "",
    kind: str = "OUTAGE",
) -> Envelope[Notice]:
    """Send a notice to the customers on these towers. Needs a policy token for action comms_send_notice."""
    _check_kind_language(kind, language)
    if not MIN_MESSAGE <= len(message.strip()) <= MAX_MESSAGE:
        raise InvalidInputError(f"message must be {MIN_MESSAGE} to {MAX_MESSAGE} characters")
    names = _towers(conn, enodeb_names)
    key = target_key(names)
    grant = verify_token(settings.signing_key(), policy_token, action=ACTION, target=key)
    now = clock.now_min(conn)
    audience = _audience(conn, names, kind, now)
    recipients = _customers(conn, audience)
    if not audience or withhold(recipients):
        raise InvalidInputError("There is nobody to tell: no affected customers on these towers (or fewer than 5 estimated)")
    text = message.strip()
    recent = conn.execute(
        "SELECT 1 FROM care_notice WHERE towers = ? AND message = ? AND ? - sent_min < ?", (key, text, now, DEDUPE_MIN)
    ).fetchone()
    if recent is not None:
        raise InvalidInputError(f"The same message was sent to these towers less than {DEDUPE_MIN} minutes ago")
    cause = _cause(conn, _affected(conn, names, now), now)
    deflected = 0 if kind == "RESTORED" else round(recipients * EXTRA_TICKET_RATE.get(cause or "", 0.0) * DEFLECTION)
    cursor = conn.execute(
        "INSERT INTO care_notice (kind, towers, language, recipients_est, message, sent_min, sent_at, approved_by, tickets_deflected_est) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (kind, key, language, recipients, text, now, clock.as_of(conn), grant.approved_by, deflected),
    )
    notice_id = f"NTC-{int(cursor.lastrowid or 0):04d}"
    conn.execute("UPDATE care_notice SET notice_id = ? WHERE seq = ?", (notice_id, cursor.lastrowid))
    conn.commit()
    row = conn.execute("SELECT * FROM care_notice WHERE seq = ?", (cursor.lastrowid,)).fetchone()
    return wrap(conn, source=SOURCE, tool="care_send_notice", data=_notice(row), ref=notice_id)


def list_notices(conn: sqlite3.Connection, limit: int = 50) -> Envelope[NoticeList]:
    """The notices sent so far, newest first. Counts only."""
    if not 1 <= limit <= 200:
        raise InvalidInputError("limit must be between 1 and 200")
    rows = conn.execute("SELECT * FROM care_notice ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
    data = NoticeList(notices=[_notice(r) for r in rows], returned=len(rows))
    return wrap(conn, source=SOURCE, tool="care_list_notices", data=data)
