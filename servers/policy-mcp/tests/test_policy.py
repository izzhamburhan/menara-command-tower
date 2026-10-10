from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core import settings
from menara_core.errors import (
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
    TokenError,
)
from menara_core.tokens import verify_token
from policy_mcp import tools


def _rule(decision: object, name: str) -> object:
    return next(r for r in decision.rules if r.rule == name)  # type: ignore[attr-defined]


# ---------- the decision ----------


def test_small_reversible_action_is_auto_allowed_with_a_valid_token(conn: sqlite3.Connection, quiet_tower: str) -> None:
    env = tools.check_action(conn, "ran_reset_cell", [quiet_tower], confidence=0.95)
    d = env.data
    assert env.synthetic is True
    assert d.decision == "allow" and d.approval_id is not None and d.token is not None
    assert d.reason == "All auto-allow conditions are met" and not d.touches_emergency
    grant = verify_token(settings.signing_key(), d.token, action="ran_reset_cell", target=quiet_tower)
    assert grant.approved_by == "policy:auto"
    assert env.evidence[0].tool == "policy_check_action"
    assert tools.get_approval(conn, d.approval_id).data.status == "AUTO_ALLOWED"


def test_the_flood_tilt_needs_a_human(conn: sqlite3.Connection) -> None:
    d = tools.check_action(conn, "ran_tilt_cells", ["KKRI-0143", "KKRI-0144"], confidence=0.95).data
    assert d.decision == "ask" and d.token is None and d.approval_id is not None
    assert d.affected_subscribers == 820 + 790
    assert [r.rule for r in d.rules if not r.passed] == ["emergency_coverage", "subscriber_impact"]
    assert d.touches_emergency is True  # KKRI-0144 serves a clinic
    assert tools.get_approval(conn, d.approval_id).data.status == "PENDING"


def test_cell_ids_are_normalised_to_towers(conn: sqlite3.Connection) -> None:
    d = tools.check_action(conn, "ran_tilt_cells", ["KKRI-0143-B1", "KKRI-0143-B3", "KKRI-0144"], 0.95).data
    assert d.targets == ["KKRI-0143", "KKRI-0144"]
    assert tools.get_approval(conn, d.approval_id or "APR-0000").data.target == "KKRI-0143,KKRI-0144"


def test_emergency_coverage_always_asks(conn: sqlite3.Connection) -> None:
    d = tools.check_action(conn, "ran_reset_cell", ["KKRI-0142"], confidence=0.99).data
    assert d.decision == "ask" and d.touches_emergency is True
    assert not _rule(d, "emergency_coverage").passed  # type: ignore[attr-defined]


def test_low_confidence_asks(conn: sqlite3.Connection, quiet_tower: str) -> None:
    d = tools.check_action(conn, "ran_reset_cell", [quiet_tower], confidence=0.8).data
    assert d.decision == "ask" and not _rule(d, "confidence").passed  # type: ignore[attr-defined]


def test_peak_hours_ask(conn: sqlite3.Connection, quiet_tower: str, set_clock: Callable[[int], None]) -> None:
    set_clock(11 * 60 + 30)  # 07:00 + 11.5 h = 18:30 local
    d = tools.check_action(conn, "ran_reset_cell", [quiet_tower], confidence=0.95).data
    assert d.decision == "ask" and not _rule(d, "off_peak").passed  # type: ignore[attr-defined]
    assert tools.get_status(conn).data.peak_hour_now is True


@pytest.mark.parametrize("action", ["drone_dispatch", "workforce_create_order", "comms_send_notice", "hardware_replace"])
def test_human_decision_actions_always_ask(conn: sqlite3.Connection, quiet_tower: str, action: str) -> None:
    d = tools.check_action(conn, action, [quiet_tower], confidence=1.0).data
    assert d.decision == "ask" and not _rule(d, "human_decision_required").passed  # type: ignore[attr-defined]


def test_unknown_action_is_denied_and_opens_no_approval(conn: sqlite3.Connection, quiet_tower: str) -> None:
    d = tools.check_action(conn, "launch_missiles", [quiet_tower], confidence=1.0).data
    assert d.decision == "deny" and d.approval_id is None and d.token is None
    assert tools.list_approvals(conn).data.returned == 0


def test_a_rollback_skips_risk_rules_but_not_the_kill_switch(conn: sqlite3.Connection, human_key: str) -> None:
    d = tools.check_action(conn, "ran_revert_tilt", ["KKRI-0142", "KKRI-0143"], confidence=0.1).data
    assert d.decision == "allow" and d.token is not None
    tools.set_kill_switch(conn, True, "tester")
    assert tools.check_action(conn, "ran_revert_tilt", ["KKRI-0143"], confidence=1.0).data.decision == "deny"


def test_confidence_and_targets_are_validated(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.check_action(conn, "ran_reset_cell", ["KKRI-0143"], confidence=1.5)
    with pytest.raises(InvalidInputError):
        tools.check_action(conn, "ran_reset_cell", [], confidence=0.9)
    with pytest.raises(InvalidInputError):
        tools.check_action(conn, "ran_reset_cell", ["KKRI-0143"] * 51, confidence=0.9)
    with pytest.raises(InvalidInputError):
        tools.check_action(conn, "ran_reset_cell", ["bad"], confidence=0.9)
    with pytest.raises(NotFoundError):
        tools.check_action(conn, "ran_reset_cell", ["ZZZZ-9999"], confidence=0.9)


# ---------- approvals ----------


def _pending(conn: sqlite3.Connection) -> str:
    d = tools.check_action(conn, "drone_dispatch", ["KKRI-0142"], confidence=0.93).data
    assert d.approval_id is not None
    return d.approval_id


def test_a_human_approval_returns_a_token_for_exactly_that_action(conn: sqlite3.Connection, human_key: str) -> None:
    approval_id = _pending(conn)
    grant = tools.approve(conn, approval_id, "izzham", human_key, note="Go").data
    assert grant.approved_by == "human:izzham" and grant.token_expires_in_s == 300
    verify_token(settings.signing_key(), grant.token, action="drone_dispatch", target="KKRI-0142")
    with pytest.raises(TokenError, match="different"):
        verify_token(settings.signing_key(), grant.token, action="ran_tilt_cells", target="KKRI-0142")
    approval = tools.get_approval(conn, approval_id).data
    assert approval.status == "APPROVED" and approval.decided_by == "human:izzham"


def test_the_agent_cannot_approve_without_the_key(conn: sqlite3.Connection) -> None:
    approval_id = _pending(conn)
    with pytest.raises(PermissionDeniedError):
        tools.approve(conn, approval_id, "agent", "guess")
    assert tools.get_approval(conn, approval_id).data.status == "PENDING"


def test_an_approval_can_only_be_decided_once(conn: sqlite3.Connection, human_key: str) -> None:
    approval_id = _pending(conn)
    tools.approve(conn, approval_id, "izzham", human_key)
    with pytest.raises(InvalidInputError, match="already APPROVED"):
        tools.approve(conn, approval_id, "izzham", human_key)
    with pytest.raises(InvalidInputError, match="already APPROVED"):
        tools.reject(conn, approval_id, "izzham", human_key)


def test_rejection_closes_the_request_without_a_token(conn: sqlite3.Connection, human_key: str) -> None:
    approval_id = _pending(conn)
    rejected = tools.reject(conn, approval_id, "izzham", human_key, note="Too risky").data
    assert rejected.status == "REJECTED"
    with pytest.raises(InvalidInputError):
        tools.record_outcome(conn, approval_id, "SUCCEEDED")


def test_approver_name_is_validated_and_ids_checked(conn: sqlite3.Connection, human_key: str) -> None:
    approval_id = _pending(conn)
    with pytest.raises(InvalidInputError):
        tools.approve(conn, approval_id, "  ", human_key)
    with pytest.raises(InvalidInputError):
        tools.get_approval(conn, "1")
    with pytest.raises(NotFoundError):
        tools.get_approval(conn, "APR-9999")


def test_nothing_can_be_approved_while_the_kill_switch_is_on(conn: sqlite3.Connection, human_key: str) -> None:
    approval_id = _pending(conn)
    tools.set_kill_switch(conn, True, "operator")
    with pytest.raises(InvalidInputError, match="Kill switch"):
        tools.approve(conn, approval_id, "izzham", human_key)


# ---------- outcomes ----------


def test_outcomes_are_recorded_for_authorised_actions(conn: sqlite3.Connection, quiet_tower: str) -> None:
    approval_id = tools.check_action(conn, "ran_reset_cell", [quiet_tower], confidence=0.95).data.approval_id
    assert approval_id is not None
    done = tools.record_outcome(conn, approval_id, "FAILED", "KPIs did not improve").data
    assert done.outcome == "FAILED" and done.outcome_detail == "KPIs did not improve"
    with pytest.raises(InvalidInputError):
        tools.record_outcome(conn, approval_id, "WORKED")


def test_a_pending_request_cannot_report_an_outcome(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError, match="never authorised"):
        tools.record_outcome(conn, _pending(conn), "SUCCEEDED")


# ---------- kill switch, cap, settings, audit ----------


def test_kill_switch_denies_everything_and_only_a_human_turns_it_off(conn: sqlite3.Connection, quiet_tower: str, human_key: str) -> None:
    assert tools.set_kill_switch(conn, True, "operator").data.kill_switch is True
    assert tools.get_status(conn).data.kill_switch is True
    d = tools.check_action(conn, "ran_reset_cell", [quiet_tower], confidence=0.99).data
    assert d.decision == "deny" and "Kill switch is ON" in d.reason
    with pytest.raises(PermissionDeniedError):
        tools.set_kill_switch(conn, False, "agent", approver_key="nope")
    assert tools.set_kill_switch(conn, False, "izzham", human_key).data.kill_switch is False
    assert tools.check_action(conn, "ran_reset_cell", [quiet_tower], confidence=0.99).data.decision == "allow"


def test_hourly_cap_denies_further_actions(conn: sqlite3.Connection, quiet_tower: str, human_key: str, set_clock: Callable[[int], None]) -> None:
    tools.update_setting(conn, "max_actions_per_hour", "2", "izzham", human_key)
    for _ in range(2):
        assert tools.check_action(conn, "ran_reset_cell", [quiet_tower], 0.95).data.decision == "allow"
    third = tools.check_action(conn, "ran_reset_cell", [quiet_tower], 0.95).data
    assert third.decision == "deny" and "2 of 2" in third.reason
    set_clock(90)  # the earlier actions are now more than an hour old
    assert tools.check_action(conn, "ran_reset_cell", [quiet_tower], 0.95).data.decision == "allow"


def test_settings_change_decisions_and_need_the_key(conn: sqlite3.Connection, human_key: str) -> None:
    with pytest.raises(PermissionDeniedError):
        tools.update_setting(conn, "auto_allow_max_subscribers", "5000", "agent", "x")
    tools.update_setting(conn, "auto_allow_max_subscribers", "5000", "izzham", human_key)
    d = tools.check_action(conn, "ran_tilt_cells", ["KKRI-0143"], confidence=0.95).data
    assert d.decision == "allow" and d.token is not None  # 820 subscribers, no emergency site on KKRI-0143
    for key, value in (("nope", "1"), ("max_actions_per_hour", "abc"), ("peak_start_hour", "99")):
        with pytest.raises(InvalidInputError):
            tools.update_setting(conn, key, value, "izzham", human_key)


def test_every_step_is_audited(conn: sqlite3.Connection, human_key: str) -> None:
    approval_id = _pending(conn)
    tools.approve(conn, approval_id, "izzham", human_key)
    tools.record_outcome(conn, approval_id, "SUCCEEDED", "done")
    tools.set_kill_switch(conn, True, "operator")
    entries = tools.get_audit(conn).data.entries
    assert [e.decision for e in entries] == ["on", "succeeded", "approved", "ask"]
    assert entries[2].actor == "human:izzham" and entries[3].actor == "policy-mcp"
    with pytest.raises(InvalidInputError):
        tools.get_audit(conn, limit=0)


def test_status_and_listing(conn: sqlite3.Connection) -> None:
    _pending(conn)
    status = tools.get_status(conn).data
    assert status.pending_approvals == 1 and status.kill_switch is False
    assert status.settings["auto_allow_max_subscribers"] == "500"
    assert "drone_dispatch" in status.known_actions
    assert tools.list_approvals(conn, status="PENDING").data.returned == 1
    with pytest.raises(InvalidInputError):
        tools.list_approvals(conn, status="MAYBE")


def test_policy_cannot_write_other_tables(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("UPDATE tower_subscribers SET subscribers_est = 0")