"""enterprise-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Owns `sla_credit` (service credits that were approved and issued). Reads, read-only: `enterprise_account`, `tower`,
`tower_state`. The companies are fictional and every value, rate and penalty is invented.

Model: an account on a tower that is DOWN accrues its penalty rate per hour; on a DEGRADED tower a quarter of it. The
revenue at risk per hour is the monthly value spread over 720 hours. A credit is the hours credited times the penalty
rate, capped at the monthly value. Issuing a credit moves money, so it needs a signed policy token for
`enterprise_issue_credit` (policy always asks a human).
"""

from __future__ import annotations

import sqlite3

from menara_core import clock, settings
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km
from menara_core.ids import parse_enodeb, target_key
from menara_core.tokens import verify_token

from enterprise_mcp.models import (
    Account,
    AccountList,
    AtRisk,
    Centre,
    Credit,
    RevenueAtRisk,
)

SOURCE = "enterprise-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"sla_credit"})
ACTION = "enterprise_issue_credit"
HOURS_PER_MONTH = 720.0
DEGRADED_FACTOR = 0.25
PROJECTION_HOURS = 2.0
MIN_HOURS, MAX_HOURS = 0.5, 72.0
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
MAX_LIMIT = 200
MAX_TOWERS = 50
FACTOR = {"DOWN": 1.0, "DEGRADED": DEGRADED_FACTOR, "UP": 0.0}


def _states(conn: sqlite3.Connection, tower: str, now: int) -> list[tuple[int, str]]:
    return [
        (r["t_min"], r["status"])
        for r in conn.execute("SELECT t_min, status FROM tower_state WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min", (tower, now))
    ]


def _status(conn: sqlite3.Connection, tower: str, now: int) -> str:
    rows = _states(conn, tower, now)
    return rows[-1][1] if rows else "UP"


def _outage(conn: sqlite3.Connection, tower: str, now: int) -> tuple[int, float]:
    """(minutes since the current run of DEGRADED or DOWN began, the weighted outage minutes inside it)."""
    rows = _states(conn, tower, now)
    run: list[tuple[int, str]] = []
    for row in reversed(rows):
        if row[1] == "UP":
            break
        run.append(row)
    run.reverse()
    if not run:
        return 0, 0.0
    weighted = 0.0
    for i, (start, status) in enumerate(run):
        end = run[i + 1][0] if i + 1 < len(run) else now
        weighted += max(0, end - start) * FACTOR[status]
    return now - run[0][0], weighted


def _credits(conn: sqlite3.Connection, account_id: str) -> float:
    return float(conn.execute("SELECT COALESCE(SUM(amount_rm), 0) FROM sla_credit WHERE account_id = ?", (account_id,)).fetchone()[0])


def _at_risk(conn: sqlite3.Connection, row: sqlite3.Row, now: int) -> AtRisk | None:
    status = _status(conn, row["enodeb_name"], now)
    if status == "UP":
        return None
    minutes, weighted = _outage(conn, row["enodeb_name"], now)
    rate = row["penalty_rm_per_hour"]
    accrued = round(rate * weighted / 60.0, 2)
    projected = round(rate * PROJECTION_HOURS * FACTOR[status], 2)
    credits = round(_credits(conn, row["account_id"]), 2)
    return AtRisk(
        account_id=row["account_id"], name=row["name"], sector=row["sector"], enodeb_name=row["enodeb_name"], status=status,
        outage_min=minutes, monthly_value_rm=row["monthly_value_rm"], revenue_per_hour_rm=round(row["monthly_value_rm"] / HOURS_PER_MONTH, 2),
        penalty_rm_per_hour=rate, penalty_accrued_rm=accrued, projected_penalty_2h_rm=projected, credits_rm=credits,
        net_exposure_rm=round(accrued + projected - credits, 2),
    )


def _check_circle(lat: float, lng: float, radius_km: float) -> None:
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")


def _accounts_in(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float) -> list[tuple[sqlite3.Row, float]]:
    min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
    found = []
    for row in conn.execute(
        "SELECT a.*, t.lat, t.lng FROM enterprise_account a JOIN tower t ON t.enodeb_name = a.enodeb_name "
        "WHERE t.lat BETWEEN ? AND ? AND t.lng BETWEEN ? AND ? ORDER BY a.account_id",
        (max(min_lat, -90.0), min(max_lat, 90.0), max(min_lng, -180.0), min(max_lng, 180.0)),
    ):
        distance = haversine_km(lat, lng, row["lat"], row["lng"])
        if distance <= radius_km:
            found.append((row, distance))
    return found


def get_revenue_at_risk(
    conn: sqlite3.Connection,
    enodeb_names: list[str] | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_km: float = 15.0,
) -> Envelope[RevenueAtRisk]:
    """Business customers on towers that are DOWN or DEGRADED: revenue and SLA penalty at risk, net of credits."""
    now = clock.now_min(conn)
    rows: list[sqlite3.Row]
    if enodeb_names:
        if len(enodeb_names) > MAX_TOWERS:
            raise InvalidInputError(f"Give at most {MAX_TOWERS} towers")
        names = list(dict.fromkeys(parse_enodeb(n) for n in enodeb_names))
        for name in names:
            if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
                raise NotFoundError(f"Tower {name} not found")
        marks = ", ".join("?" for _ in names)
        rows = conn.execute(f"SELECT * FROM enterprise_account WHERE enodeb_name IN ({marks}) ORDER BY account_id", names).fetchall()
        ref = target_key(names)
    elif lat is not None and lng is not None:
        _check_circle(lat, lng, radius_km)
        rows = [r for r, _ in _accounts_in(conn, lat, lng, radius_km)]
        ref = f"{lat},{lng},{radius_km}km"
    else:
        raise InvalidInputError("Give enodeb_names, or a centre (lat and lng) with radius_km")
    accounts = [a for a in (_at_risk(conn, r, now) for r in rows) if a is not None]
    data = RevenueAtRisk(
        accounts=accounts,
        revenue_per_hour_rm=round(sum(a.revenue_per_hour_rm for a in accounts), 2),
        penalty_accrued_rm=round(sum(a.penalty_accrued_rm for a in accounts), 2),
        projected_penalty_2h_rm=round(sum(a.projected_penalty_2h_rm for a in accounts), 2),
        credits_rm=round(sum(a.credits_rm for a in accounts), 2),
        net_exposure_rm=round(sum(a.net_exposure_rm for a in accounts), 2),
    )
    return wrap(conn, source=SOURCE, tool="enterprise_get_revenue_at_risk", data=data, ref=ref)


def list_accounts(conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 15.0, limit: int = 50) -> Envelope[AccountList]:
    """Business customers in a circle with their current service state, nearest first."""
    _check_circle(lat, lng, radius_km)
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    now = clock.now_min(conn)
    found = sorted(_accounts_in(conn, lat, lng, radius_km), key=lambda pair: (pair[1], pair[0]["account_id"]))[:limit]
    accounts = [
        Account(
            account_id=r["account_id"], name=r["name"], sector=r["sector"], enodeb_name=r["enodeb_name"], status=_status(conn, r["enodeb_name"], now),
            plan=r["plan"], monthly_value_rm=r["monthly_value_rm"], sla_availability_pct=r["sla_availability_pct"],
            penalty_rm_per_hour=r["penalty_rm_per_hour"], distance_km=round(d, 2),
        )
        for r, d in found
    ]
    data = AccountList(center=Centre(lat=lat, lng=lng), radius_km=radius_km, accounts=accounts, returned=len(accounts))
    return wrap(conn, source=SOURCE, tool="enterprise_list_accounts", data=data, ref=f"{lat},{lng},{radius_km}km")


def issue_credit(conn: sqlite3.Connection, account_id: str, hours: float, policy_token: str, reason: str = "") -> Envelope[Credit]:
    """Credit an affected account for `hours` of service from now. Needs a policy token for enterprise_issue_credit."""
    if not MIN_HOURS <= hours <= MAX_HOURS:
        raise InvalidInputError(f"hours must be between {MIN_HOURS:g} and {MAX_HOURS:g}")
    account = conn.execute("SELECT * FROM enterprise_account WHERE account_id = ?", (account_id,)).fetchone()
    if account is None:
        raise NotFoundError(f"Account {account_id} not found")
    grant = verify_token(settings.signing_key(), policy_token, action=ACTION, target=target_key([account["enodeb_name"]]))
    now = clock.now_min(conn)
    if not any(status != "UP" for _, status in _states(conn, account["enodeb_name"], now)):
        raise InvalidInputError(f"{account_id} is on {account['enodeb_name']}, which has not been affected: no credit is due")
    end = now + round(hours * 60)
    clash = conn.execute(
        "SELECT credit_id FROM sla_credit WHERE account_id = ? AND from_min < ? AND from_min + hours * 60 > ?", (account_id, end, now)
    ).fetchone()
    if clash is not None:
        raise InvalidInputError(f"{clash['credit_id']} already credits this account for part of those hours")
    amount = round(min(hours * account["penalty_rm_per_hour"], account["monthly_value_rm"]), 2)
    cursor = conn.execute(
        "INSERT INTO sla_credit (account_id, from_min, hours, amount_rm, issued_min, issued_at, approved_by, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, now, hours, amount, now, clock.as_of(conn), grant.approved_by, reason.strip()[:300]),
    )
    credit_id = f"CRD-{int(cursor.lastrowid or 0):04d}"
    conn.execute("UPDATE sla_credit SET credit_id = ? WHERE seq = ?", (credit_id, cursor.lastrowid))
    conn.commit()
    data = Credit(credit_id=credit_id, account_id=account_id, from_min=now, hours=hours, amount_rm=amount, issued_at=clock.as_of(conn), approved_by=grant.approved_by)
    return wrap(conn, source=SOURCE, tool="enterprise_issue_credit", data=data, ref=credit_id)
