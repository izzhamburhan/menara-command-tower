"""policy-mcp tool logic.

Decides allow, ask or deny for every real-world action, issues HMAC-signed tokens that action MCPs verify
locally, tracks human approvals, and keeps the audit log and kill switch. It reads tower_subscribers and
critical_site (read-only) so it computes the impact itself instead of trusting the caller. It writes only
policy_setting, approval and audit_log.
"""

from __future__ import annotations

import hmac
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from menara_core import clock, settings
from menara_core.audit import append_audit
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError, PermissionDeniedError
from menara_core.ids import (
    CELL_RE,
    enodeb_of_cell,
    parse_approval_id,
    parse_enodeb,
    target_key,
)
from menara_core.tokens import issue_token

from policy_mcp.models import (
    Approval,
    ApprovalList,
    ApprovalStatus,
    AuditEntry,
    AuditTrail,
    Decision,
    KillSwitch,
    PolicyDecision,
    PolicyStatus,
    RuleResult,
    SettingChange,
    TokenGrant,
)

SOURCE = "policy-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"policy_setting", "approval", "audit_log"})
MAX_TARGETS = 50
MAX_LIMIT = 500
OUTCOMES = {"SUCCEEDED", "FAILED", "ROLLED_BACK"}
STATUSES = {"PENDING", "AUTO_ALLOWED", "APPROVED", "REJECTED"}
EDITABLE_SETTINGS: dict[str, tuple[float, float]] = {
    "auto_allow_max_subscribers": (0, 1_000_000),
    "auto_allow_min_confidence": (0.0, 1.0),
    "peak_start_hour": (0, 23),
    "peak_end_hour": (1, 24),
    "max_actions_per_hour": (0, 1000),
    "token_ttl_s": (10, 3600),
}


@dataclass(frozen=True)
class ActionProfile:
    description: str
    always_ask: str | None = None  # reason a human must decide, whatever the numbers say
    rollback: bool = False  # a rollback skips the risk rules (never the kill switch or the cap)


ACTIONS: dict[str, ActionProfile] = {
    "ran_reset_cell": ActionProfile("Soft reset of a hung cell"),
    "ran_tilt_cells": ActionProfile("Change antenna tilt on cells (simulate with twin-mcp first)"),
    "ran_revert_tilt": ActionProfile("Roll back an earlier RAN change", rollback=True),
    "drone_dispatch": ActionProfile(
        "Dispatch a drone to inspect a tower",
        always_ask="Sending a drone into an affected area needs a human decision.",
    ),
    "workforce_create_order": ActionProfile(
        "Create a field work order", always_ask="A work order commits field staff."
    ),
    "comms_send_notice": ActionProfile(
        "Send a customer notice", always_ask="A customer notice cannot be unsent."
    ),
    "hardware_replace": ActionProfile(
        "Replace hardware", always_ask="Hardware replacement is never automated."
    ),
    "energy_sleep_cells": ActionProfile("Put idle capacity layers to sleep for the night (energy-mcp)"),
    "exposure_book_qod": ActionProfile(
        "Book quality on demand for a customer (exposure-mcp)", always_ask="Selling a network service needs a human decision."
    ),
    "enterprise_issue_credit": ActionProfile(
        "Issue an SLA service credit to a business customer (enterprise-mcp)", always_ask="Moving money needs a human decision."
    ),
}


# ---------- settings ----------


@dataclass(frozen=True)
class Config:
    kill_switch: bool
    max_subscribers: int
    min_confidence: float
    peak_start: int
    peak_end: int
    max_per_hour: int
    token_ttl_s: int


def _raw_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM policy_setting ORDER BY key")}


def _config(conn: sqlite3.Connection) -> Config:
    raw = _raw_settings(conn)
    return Config(
        kill_switch=raw.get("kill_switch", "0") == "1",
        max_subscribers=int(raw["auto_allow_max_subscribers"]),
        min_confidence=float(raw["auto_allow_min_confidence"]),
        peak_start=int(raw["peak_start_hour"]),
        peak_end=int(raw["peak_end_hour"]),
        max_per_hour=int(raw["max_actions_per_hour"]),
        token_ttl_s=int(raw["token_ttl_s"]),
    )


def _is_peak(conn: sqlite3.Connection, config: Config) -> bool:
    hour = datetime.fromisoformat(clock.as_of(conn)).hour
    return config.peak_start <= hour < config.peak_end


def _actions_last_hour(conn: sqlite3.Connection) -> int:
    now = clock.now_min(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM approval WHERE status IN ('AUTO_ALLOWED', 'APPROVED') "
        "AND COALESCE(decided_min, requested_min) > ?",
        (now - 60,),
    ).fetchone()
    return int(row[0])


def _check_human(key: str) -> None:
    if not hmac.compare_digest(key.encode(), settings.approver_key().encode()):
        raise PermissionDeniedError("Invalid approver key: only a human approver may do this")


# ---------- impact ----------


def _normalise_targets(conn: sqlite3.Connection, targets: list[str]) -> list[str]:
    if not targets:
        raise InvalidInputError("targets must not be empty")
    if len(targets) > MAX_TARGETS:
        raise InvalidInputError(f"at most {MAX_TARGETS} targets per action")
    towers: set[str] = set()
    for raw in targets:
        text = raw.strip()
        name = enodeb_of_cell(text) if CELL_RE.match(text) else parse_enodeb(text)
        if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
            raise NotFoundError(f"Tower {name} not found")
        towers.add(name)
    return sorted(towers)


def _impact(conn: sqlite3.Connection, towers: list[str]) -> tuple[int, bool]:
    subscribers = 0
    emergency = False
    for name in towers:
        row = conn.execute("SELECT subscribers_est FROM tower_subscribers WHERE enodeb_name = ?", (name,)).fetchone()
        subscribers += int(row["subscribers_est"]) if row else 0
        hit = conn.execute(
            "SELECT 1 FROM critical_site WHERE serving_enodeb = ? AND emergency_service = 1 LIMIT 1", (name,)
        ).fetchone()
        emergency = emergency or hit is not None
    return subscribers, emergency


# ---------- check_action ----------


def _evaluate(
    conn: sqlite3.Connection,
    config: Config,
    action: str,
    profile: ActionProfile | None,
    confidence: float,
    subscribers: int,
    emergency: bool,
) -> list[RuleResult]:
    rules = [
        RuleResult(
            rule="known_action",
            on_fail="deny",
            passed=profile is not None,
            detail=f"{action} is a known action" if profile else f"{action} is not a recognised action",
        ),
        RuleResult(
            rule="kill_switch_off",
            on_fail="deny",
            passed=not config.kill_switch,
            detail="Kill switch is off" if not config.kill_switch else "Kill switch is ON: all actions are blocked",
        ),
    ]
    used = _actions_last_hour(conn)
    rules.append(
        RuleResult(
            rule="hourly_action_cap",
            on_fail="deny",
            passed=used < config.max_per_hour,
            detail=f"{used} of {config.max_per_hour} actions authorised in the last hour",
        )
    )
    if profile is None or profile.rollback:
        return rules
    rules.append(
        RuleResult(
            rule="human_decision_required",
            on_fail="ask",
            passed=profile.always_ask is None,
            detail=profile.always_ask or "No mandatory human decision for this action",
        )
    )
    rules.append(
        RuleResult(
            rule="emergency_coverage",
            on_fail="ask",
            passed=not emergency,
            detail="A target serves emergency-service sites (clinic, hospital, police, fire)"
            if emergency
            else "No emergency-service sites on the targets",
        )
    )
    rules.append(
        RuleResult(
            rule="subscriber_impact",
            on_fail="ask",
            passed=subscribers < config.max_subscribers,
            detail=f"{subscribers} subscribers affected; auto-allow below {config.max_subscribers}",
        )
    )
    rules.append(
        RuleResult(
            rule="confidence",
            on_fail="ask",
            passed=confidence >= config.min_confidence,
            detail=f"Confidence {confidence:g}; auto-allow at {config.min_confidence:g} or more",
        )
    )
    peak = _is_peak(conn, config)
    rules.append(
        RuleResult(
            rule="off_peak",
            on_fail="ask",
            passed=not peak,
            detail=f"Peak hours are {config.peak_start:02d}:00 to {config.peak_end:02d}:00 local"
            + ("; it is peak now" if peak else "; it is off-peak now"),
        )
    )
    return rules


def check_action(
    conn: sqlite3.Connection, action: str, targets: list[str], confidence: float, reason: str = ""
) -> Envelope[PolicyDecision]:
    """Ask the policy engine. allow returns a signed token; ask opens an approval a human must decide."""
    if not 0.0 <= confidence <= 1.0:
        raise InvalidInputError("confidence must be between 0 and 1")
    towers = _normalise_targets(conn, targets)
    config = _config(conn)
    profile = ACTIONS.get(action)
    subscribers, emergency = _impact(conn, towers)
    rules = _evaluate(conn, config, action, profile, confidence, subscribers, emergency)
    failed = [r for r in rules if not r.passed]
    decision: Decision = "allow"
    if any(r.on_fail == "deny" for r in failed):
        decision = "deny"
    elif failed:
        decision = "ask"
    why = failed[0].detail if failed else "All auto-allow conditions are met"
    if reason.strip():
        why = f"{why} (agent reason: {reason.strip()[:200]})"

    key = target_key(towers)
    approval_id: str | None = None
    token: str | None = None
    now, stamp = clock.now_min(conn), clock.as_of(conn)
    if decision != "deny":
        status = "PENDING" if decision == "ask" else "AUTO_ALLOWED"
        cursor = conn.execute(
            "INSERT INTO approval (action, target, status, confidence, affected_subscribers, touches_emergency, "
            "reason, requested_min, requested_at, decided_min, decided_at, decided_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                action,
                key,
                status,
                confidence,
                subscribers,
                int(emergency),
                why,
                now,
                stamp,
                now if decision == "allow" else None,
                stamp if decision == "allow" else None,
                "policy:auto" if decision == "allow" else None,
            ),
        )
        approval_id = f"APR-{int(cursor.lastrowid or 0):04d}"
        conn.execute("UPDATE approval SET approval_id = ? WHERE seq = ?", (approval_id, cursor.lastrowid))
        conn.commit()
        if decision == "allow":
            token = issue_token(
                settings.signing_key(), action=action, target=key, approved_by="policy:auto", ttl_s=config.token_ttl_s
            )
    append_audit(
        conn,
        actor=SOURCE,
        action=action,
        target=key,
        decision=decision,
        detail={"approval_id": approval_id, "confidence": confidence, "reason": why, "subscribers": subscribers},
    )
    data = PolicyDecision(
        action=action,
        targets=towers,
        decision=decision,
        reason=why,
        rules=rules,
        affected_subscribers=subscribers,
        touches_emergency=emergency,
        approval_id=approval_id,
        token=token,
        token_expires_in_s=config.token_ttl_s if token else None,
    )
    return wrap(conn, source=SOURCE, tool="policy_check_action", data=data, ref=approval_id or key)


# ---------- approvals ----------


def _approval(row: sqlite3.Row) -> Approval:
    return Approval(
        approval_id=row["approval_id"],
        action=row["action"],
        target=row["target"],
        status=cast(ApprovalStatus, row["status"]),
        confidence=row["confidence"],
        affected_subscribers=row["affected_subscribers"],
        touches_emergency=bool(row["touches_emergency"]),
        reason=row["reason"],
        requested_at=row["requested_at"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        outcome=row["outcome"],
        outcome_detail=row["outcome_detail"],
    )


def _require_approval(conn: sqlite3.Connection, approval_id: str) -> sqlite3.Row:
    aid = parse_approval_id(approval_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM approval WHERE approval_id = ?", (aid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Approval {aid} not found")
    return row


def get_approval(conn: sqlite3.Connection, approval_id: str) -> Envelope[Approval]:
    row = _require_approval(conn, approval_id)
    return wrap(conn, source=SOURCE, tool="policy_get_approval", data=_approval(row), ref=row["approval_id"])


def list_approvals(
    conn: sqlite3.Connection, status: str | None = None, limit: int = 50
) -> Envelope[ApprovalList]:
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    rows = conn.execute(
        "SELECT * FROM approval WHERE (? IS NULL OR status = ?) ORDER BY seq DESC LIMIT ?", (status, status, limit)
    ).fetchall()
    items = [_approval(r) for r in rows]
    return wrap(conn, source=SOURCE, tool="policy_list_approvals", data=ApprovalList(approvals=items, returned=len(items)))


def _decide(
    conn: sqlite3.Connection, approval_id: str, approver: str, approver_key: str, approve: bool, note: str | None
) -> sqlite3.Row:
    _check_human(approver_key)
    who = approver.strip()
    if not who or len(who) > 60:
        raise InvalidInputError("approver must be 1-60 characters")
    row = _require_approval(conn, approval_id)
    if row["status"] != "PENDING":
        raise InvalidInputError(f"Approval {row['approval_id']} is already {row['status']}")
    config = _config(conn)
    if approve and config.kill_switch:
        raise InvalidInputError("Kill switch is ON: no action can be approved")
    if approve and _actions_last_hour(conn) >= config.max_per_hour:
        raise InvalidInputError("Hourly action cap reached: no further action can be approved")
    stamp = clock.as_of(conn)
    conn.execute(
        "UPDATE approval SET status = ?, decided_by = ?, decided_min = ?, decided_at = ?, outcome_detail = COALESCE(?, outcome_detail) "
        "WHERE approval_id = ?",
        ("APPROVED" if approve else "REJECTED", f"human:{who}", clock.now_min(conn), stamp, note, row["approval_id"]),
    )
    conn.commit()
    append_audit(
        conn,
        actor=f"human:{who}",
        action=row["action"],
        target=row["target"],
        decision="approved" if approve else "rejected",
        detail={"approval_id": row["approval_id"], "note": note or ""},
    )
    return row


def approve(
    conn: sqlite3.Connection, approval_id: str, approver: str, approver_key: str, note: str | None = None
) -> Envelope[TokenGrant]:
    """A human approves a pending action; returns the signed token the action MCP will verify."""
    row = _decide(conn, approval_id, approver, approver_key, True, note)
    config = _config(conn)
    who = f"human:{approver.strip()}"
    token = issue_token(
        settings.signing_key(), action=row["action"], target=row["target"], approved_by=who, ttl_s=config.token_ttl_s
    )
    data = TokenGrant(
        approval_id=row["approval_id"],
        action=row["action"],
        target=row["target"],
        approved_by=who,
        token=token,
        token_expires_in_s=config.token_ttl_s,
    )
    return wrap(conn, source=SOURCE, tool="policy_approve", data=data, ref=row["approval_id"])


def reject(
    conn: sqlite3.Connection, approval_id: str, approver: str, approver_key: str, note: str | None = None
) -> Envelope[Approval]:
    row = _decide(conn, approval_id, approver, approver_key, False, note)
    return wrap(
        conn,
        source=SOURCE,
        tool="policy_reject",
        data=_approval(_require_approval(conn, row["approval_id"])),
        ref=row["approval_id"],
    )


def record_outcome(
    conn: sqlite3.Connection, approval_id: str, outcome: str, detail: str = ""
) -> Envelope[Approval]:
    """Write what happened back: SUCCEEDED, FAILED or ROLLED_BACK. Only for approved or auto-allowed actions."""
    row = _require_approval(conn, approval_id)
    if outcome not in OUTCOMES:
        raise InvalidInputError(f"outcome must be one of {sorted(OUTCOMES)}")
    if row["status"] not in {"AUTO_ALLOWED", "APPROVED"}:
        raise InvalidInputError(f"Approval {row['approval_id']} is {row['status']}; it never authorised an action")
    text = detail.strip()[:500]
    conn.execute(
        "UPDATE approval SET outcome = ?, outcome_detail = ? WHERE approval_id = ?",
        (outcome, text, row["approval_id"]),
    )
    conn.commit()
    append_audit(
        conn,
        actor=SOURCE,
        action=row["action"],
        target=row["target"],
        decision=outcome.lower(),
        detail={"approval_id": row["approval_id"], "detail": text},
    )
    return wrap(
        conn,
        source=SOURCE,
        tool="policy_record_outcome",
        data=_approval(_require_approval(conn, row["approval_id"])),
        ref=row["approval_id"],
    )


# ---------- status, kill switch, settings, audit ----------


def get_status(conn: sqlite3.Connection) -> Envelope[PolicyStatus]:
    config = _config(conn)
    pending = conn.execute("SELECT COUNT(*) FROM approval WHERE status = 'PENDING'").fetchone()[0]
    data = PolicyStatus(
        kill_switch=config.kill_switch,
        settings=_raw_settings(conn),
        peak_hour_now=_is_peak(conn, config),
        actions_last_hour=_actions_last_hour(conn),
        max_actions_per_hour=config.max_per_hour,
        pending_approvals=int(pending),
        known_actions={name: p.description for name, p in ACTIONS.items()},
    )
    return wrap(conn, source=SOURCE, tool="policy_get_status", data=data)


def set_kill_switch(
    conn: sqlite3.Connection, enabled: bool, actor: str, approver_key: str = ""
) -> Envelope[KillSwitch]:
    """Anyone can switch it ON. Only a human holding the approver key can switch it OFF."""
    who = actor.strip()
    if not who or len(who) > 60:
        raise InvalidInputError("actor must be 1-60 characters")
    if not enabled:
        _check_human(approver_key)
    conn.execute("UPDATE policy_setting SET value = ? WHERE key = 'kill_switch'", ("1" if enabled else "0",))
    conn.commit()
    append_audit(
        conn,
        actor=who,
        action="kill_switch",
        target="all",
        decision="on" if enabled else "off",
        detail={},
    )
    return wrap(
        conn, source=SOURCE, tool="policy_set_kill_switch", data=KillSwitch(kill_switch=enabled, changed_by=who)
    )


def update_setting(
    conn: sqlite3.Connection, key: str, value: str, actor: str, approver_key: str
) -> Envelope[SettingChange]:
    """Change a threshold. Human only."""
    _check_human(approver_key)
    if key not in EDITABLE_SETTINGS:
        raise InvalidInputError(f"key must be one of {sorted(EDITABLE_SETTINGS)}")
    low, high = EDITABLE_SETTINGS[key]
    try:
        number = float(value)
    except ValueError as exc:
        raise InvalidInputError(f"{key} must be a number") from exc
    if not low <= number <= high:
        raise InvalidInputError(f"{key} must be between {low:g} and {high:g}")
    who = actor.strip()
    if not who or len(who) > 60:
        raise InvalidInputError("actor must be 1-60 characters")
    stored = str(int(number)) if key != "auto_allow_min_confidence" else str(number)
    conn.execute("UPDATE policy_setting SET value = ? WHERE key = ?", (stored, key))
    conn.commit()
    append_audit(conn, actor=f"human:{who}", action="update_setting", target=key, decision="changed", detail={"value": stored})
    return wrap(
        conn,
        source=SOURCE,
        tool="policy_update_setting",
        data=SettingChange(key=key, value=stored, changed_by=f"human:{who}"),
    )


def get_audit(conn: sqlite3.Connection, limit: int = 50) -> Envelope[AuditTrail]:
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    rows = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    entries = [
        AuditEntry(
            id=r["id"],
            at=r["at"],
            actor=r["actor"],
            action=r["action"],
            target=r["target"],
            decision=r["decision"],
            detail=r["detail"],
        )
        for r in rows
    ]
    return wrap(conn, source=SOURCE, tool="policy_get_audit", data=AuditTrail(entries=entries, returned=len(entries)))
