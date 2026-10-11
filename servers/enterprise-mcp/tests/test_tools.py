"""enterprise-mcp tools: business customers, revenue and SLA penalty at risk, and service credits. Invented numbers."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from enterprise_mcp import tools
from menara_core import settings
from menara_core.errors import InvalidInputError, NotFoundError, TokenError
from menara_core.ids import target_key
from menara_core.tokens import issue_token


def token(tower: str, action: str = "enterprise_issue_credit") -> str:
    return issue_token(settings.signing_key(), action=action, target=target_key([tower]), approved_by="human:test")


def accounts_on(conn: sqlite3.Connection, tower: str) -> list[str]:
    return [r["account_id"] for r in conn.execute("SELECT account_id FROM enterprise_account WHERE enodeb_name = ? ORDER BY 1", (tower,))]


def a_healthy_account(conn: sqlite3.Connection) -> tuple[str, str]:
    row = conn.execute(
        "SELECT a.account_id, a.enodeb_name FROM enterprise_account a WHERE a.enodeb_name NOT LIKE 'KKRI-%' "
        "AND NOT EXISTS (SELECT 1 FROM tower_state s WHERE s.enodeb_name = a.enodeb_name AND s.status != 'UP') ORDER BY a.account_id LIMIT 1"
    ).fetchone()
    assert row is not None, "the test database has no account on a tower that was never affected"
    return str(row["account_id"]), str(row["enodeb_name"])


def test_accounts_on_the_down_tower_are_at_risk_with_outage_minutes_from_tower_state(conn: sqlite3.Connection) -> None:
    env = tools.get_revenue_at_risk(conn, enodeb_names=["KKRI-0142"])
    data = env.data
    assert {a.account_id for a in data.accounts} == set(accounts_on(conn, "KKRI-0142")) and len(data.accounts) == 2
    assert all(a.status == "DOWN" and a.outage_min == 240 for a in data.accounts)  # degraded at -240, down from -5
    assert env.synthetic is True and env.evidence[0].tool == "enterprise_get_revenue_at_risk"


def test_a_healthy_tower_has_no_accounts_at_risk(conn: sqlite3.Connection) -> None:
    _, tower = a_healthy_account(conn)
    data = tools.get_revenue_at_risk(conn, enodeb_names=[tower]).data
    assert data.accounts == [] and data.revenue_per_hour_rm == 0 and data.net_exposure_rm == 0


def test_revenue_per_hour_penalty_so_far_and_two_hour_projection_add_up(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(65)  # an hour after the tower went down
    data = tools.get_revenue_at_risk(conn, enodeb_names=["KKRI-0142"]).data
    for a in data.accounts:
        assert a.outage_min == 305
        assert a.revenue_per_hour_rm == round(a.monthly_value_rm / tools.HOURS_PER_MONTH, 2)
        # 235 minutes degraded (a quarter of the rate) then 70 minutes down (the full rate)
        assert a.penalty_accrued_rm == round(a.penalty_rm_per_hour * (235 * tools.DEGRADED_FACTOR + 70) / 60, 2)
        assert a.projected_penalty_2h_rm == round(a.penalty_rm_per_hour * 2, 2)
        assert a.net_exposure_rm == round(a.penalty_accrued_rm + a.projected_penalty_2h_rm - a.credits_rm, 2)
    assert data.penalty_accrued_rm == round(sum(a.penalty_accrued_rm for a in data.accounts), 2)
    assert data.revenue_per_hour_rm == round(sum(a.revenue_per_hour_rm for a in data.accounts), 2)


def test_area_and_tower_selectors_and_neither_given_is_invalid_input(conn: sqlite3.Connection) -> None:
    by_area = tools.get_revenue_at_risk(conn, lat=5.531, lng=102.197, radius_km=15.0).data
    assert {"KKRI-0142"} <= {a.enodeb_name for a in by_area.accounts}
    with pytest.raises(InvalidInputError):
        tools.get_revenue_at_risk(conn)
    with pytest.raises(InvalidInputError):
        tools.get_revenue_at_risk(conn, lat=5.5)  # a centre needs both lat and lng
    with pytest.raises(InvalidInputError):
        tools.get_revenue_at_risk(conn, lat=5.5, lng=102.1, radius_km=0.0)
    with pytest.raises(NotFoundError):
        tools.get_revenue_at_risk(conn, enodeb_names=["ZZZZ-9999"])


def test_list_accounts_in_a_circle_with_service_state(conn: sqlite3.Connection) -> None:
    data = tools.list_accounts(conn, 5.531, 102.197, 15.0).data
    states = {a.account_id: a.status for a in data.accounts}
    assert states[accounts_on(conn, "KKRI-0142")[0]] == "DOWN" and set(states.values()) <= {"UP", "DEGRADED", "DOWN"}
    assert data.returned == len(data.accounts) and all("(synthetic)" in a.name for a in data.accounts)
    with pytest.raises(InvalidInputError):
        tools.list_accounts(conn, 5.5, 102.1, 15.0, limit=0)


def test_issue_credit_needs_the_token_for_the_accounts_tower(conn: sqlite3.Connection) -> None:
    account = accounts_on(conn, "KKRI-0142")[0]
    for bad in ("not-a-token", token("KKRI-0142", action="comms_send_notice"), token("KKRI-0143")):
        with pytest.raises(TokenError):
            tools.issue_credit(conn, account, 2.0, bad, "x")


def test_issue_credit_amount_is_hours_times_penalty_capped_at_monthly_value(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(65)
    account = accounts_on(conn, "KKRI-0142")[0]
    row = conn.execute("SELECT penalty_rm_per_hour, monthly_value_rm FROM enterprise_account WHERE account_id = ?", (account,)).fetchone()
    credit = tools.issue_credit(conn, account, 2.0, token("KKRI-0142"), "flood").data
    assert credit.credit_id == "CRD-0001" and credit.account_id == account and credit.approved_by == "human:test"
    assert credit.amount_rm == round(min(2.0 * row["penalty_rm_per_hour"], row["monthly_value_rm"]), 2)
    other = accounts_on(conn, "KKRI-0142")[1]
    huge = tools.issue_credit(conn, other, 72.0, token("KKRI-0142"), "cap").data
    cap = conn.execute("SELECT monthly_value_rm, penalty_rm_per_hour FROM enterprise_account WHERE account_id = ?", (other,)).fetchone()
    assert huge.amount_rm == round(min(72.0 * cap["penalty_rm_per_hour"], cap["monthly_value_rm"]), 2)


def test_a_credit_for_an_unaffected_account_is_invalid_input(conn: sqlite3.Connection) -> None:
    account, tower = a_healthy_account(conn)
    with pytest.raises(InvalidInputError):
        tools.issue_credit(conn, account, 1.0, token(tower), "x")


def test_overlapping_credit_hours_and_bad_numbers_are_invalid_input(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(65)
    account = accounts_on(conn, "KKRI-0142")[0]
    tools.issue_credit(conn, account, 2.0, token("KKRI-0142"), "first")
    with pytest.raises(InvalidInputError):
        tools.issue_credit(conn, account, 1.0, token("KKRI-0142"), "overlaps")
    set_clock(65 + 125)  # the first credit's two hours are over
    assert tools.issue_credit(conn, account, 1.0, token("KKRI-0142"), "later").data.credit_id == "CRD-0002"
    for hours in (0.0, 0.4, 72.5):
        with pytest.raises(InvalidInputError):
            tools.issue_credit(conn, account, hours, token("KKRI-0142"), "x")
    with pytest.raises(NotFoundError):
        tools.issue_credit(conn, "ACC-9999", 1.0, token("KKRI-0142"), "x")


def test_after_a_credit_the_net_exposure_falls_and_the_credit_is_listed(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(65)
    before = tools.get_revenue_at_risk(conn, enodeb_names=["KKRI-0142"]).data
    account = accounts_on(conn, "KKRI-0142")[0]
    credit = tools.issue_credit(conn, account, 2.0, token("KKRI-0142"), "flood").data
    after = tools.get_revenue_at_risk(conn, enodeb_names=["KKRI-0142"]).data
    one = next(a for a in after.accounts if a.account_id == account)
    assert one.credits_rm == credit.amount_rm and after.credits_rm == credit.amount_rm
    assert after.net_exposure_rm == round(before.net_exposure_rm - credit.amount_rm, 2)
