"""Policy for the actions of the track servers: sleep modes, quality bookings and service credits."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core import settings
from menara_core.tokens import verify_token
from policy_mcp import tools

NEW_ACTIONS = ("energy_sleep_cells", "exposure_book_qod", "enterprise_issue_credit")


def test_the_new_actions_are_known(conn: sqlite3.Connection) -> None:
    known = tools.get_status(conn).data.known_actions
    assert all(a in known for a in NEW_ACTIONS)
    assert all(a in known for a in ("comms_send_notice", "workforce_create_order"))


@pytest.mark.parametrize("action", ["exposure_book_qod", "enterprise_issue_credit"])
def test_selling_a_service_or_moving_money_always_asks_a_human(conn: sqlite3.Connection, quiet_tower: str, action: str) -> None:
    d = tools.check_action(conn, action, [quiet_tower], confidence=1.0).data
    assert d.decision == "ask" and d.token is None and d.approval_id is not None
    assert any(r.rule == "human_decision_required" and not r.passed for r in d.rules)


def test_energy_sleep_follows_the_normal_rules_off_peak(conn: sqlite3.Connection, quiet_tower: str) -> None:
    d = tools.check_action(conn, "energy_sleep_cells", [quiet_tower], confidence=0.95).data
    assert d.decision == "allow" and d.token is not None
    grant = verify_token(settings.signing_key(), d.token, action="energy_sleep_cells", target=quiet_tower)
    assert grant.approved_by == "policy:auto"


def test_energy_sleep_asks_in_the_peak_window(conn: sqlite3.Connection, quiet_tower: str, set_clock: Callable[[int], None]) -> None:
    set_clock(11 * 60 + 30)  # 18:30 local, inside the peak window
    d = tools.check_action(conn, "energy_sleep_cells", [quiet_tower], confidence=0.95).data
    assert d.decision == "ask" and not next(r for r in d.rules if r.rule == "off_peak").passed


@pytest.mark.parametrize("action", NEW_ACTIONS)
def test_the_kill_switch_denies_the_new_actions(conn: sqlite3.Connection, quiet_tower: str, action: str) -> None:
    tools.set_kill_switch(conn, True, "tester")
    assert tools.check_action(conn, action, [quiet_tower], confidence=1.0).data.decision == "deny"


def test_the_hourly_cap_counts_the_new_actions(conn: sqlite3.Connection, quiet_tower: str, human_key: str) -> None:
    tools.update_setting(conn, "max_actions_per_hour", "2", "izzham", human_key)
    for _ in range(2):
        assert tools.check_action(conn, "energy_sleep_cells", [quiet_tower], 0.95).data.decision == "allow"
    third = tools.check_action(conn, "energy_sleep_cells", [quiet_tower], 0.95).data
    assert third.decision == "deny" and "2 of 2" in third.reason