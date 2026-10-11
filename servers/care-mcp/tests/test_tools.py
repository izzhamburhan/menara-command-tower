"""care-mcp tools: who is affected by an outage, a drafted notice, and sending it. Counts only, never people."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable

import pytest
from care_mcp import tools
from menara_core import settings
from menara_core.errors import InvalidInputError, NotFoundError, TokenError
from menara_core.ids import target_key
from menara_core.tokens import issue_token

FLOOD = ["KKRI-0142"]
ALL_CLUSTER = [f"KKRI-{n:04d}" for n in range(142, 154)]
MESSAGE = "Dear customer, service in Kuala Krai is disrupted by flooding. We are working to restore it. (synthetic demo)"


def token(names: list[str], action: str = "comms_send_notice") -> str:
    return issue_token(settings.signing_key(), action=action, target=target_key(names), approved_by="human:test")


def test_impact_counts_only_towers_that_are_down_or_degraded(conn: sqlite3.Connection) -> None:
    both = tools.get_impact(conn, ["KKRI-0142", "KKRI-0143"]).data
    assert both.affected_towers == ["KKRI-0142"] and both.affected_customers == 980
    healthy = tools.get_impact(conn, ["KKRI-0143"]).data
    assert healthy.affected_towers == [] and healthy.affected_customers == 0 and healthy.predicted_extra_tickets_1h == 0


def test_impact_predicts_extra_tickets_the_open_tickets_and_the_language_mix(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    data = tools.get_impact(conn, FLOOD).data
    assert data.cause == "FLOOD" and data.predicted_extra_tickets_if_silent > 0
    assert data.predicted_extra_tickets_1h == data.predicted_extra_tickets_if_silent  # nobody has been told yet
    assert data.open_tickets_nearby >= 30 and data.top_categories and data.top_categories[0].count >= 1
    assert abs(sum(data.language_mix.values()) - 1.0) < 0.01 and data.language_mix["ms"] > 0.7  # Kelantan
    assert data.notices_sent == 0 and data.notified_customers == 0


def test_impact_is_withheld_under_5_customers() -> None:
    assert tools.withhold(4) is True and tools.withhold(5) is False and tools.MIN_RECIPIENTS == 5


def test_the_draft_fills_the_template_in_each_language_and_is_not_sent(conn: sqlite3.Connection) -> None:
    for language in ("en", "ms", "zh", "ta"):
        draft = tools.draft_notice(conn, FLOOD, "OUTAGE", language).data
        assert "{" not in draft.message and "Kuala Krai" in draft.message and draft.language == language
    assert conn.execute("SELECT COUNT(*) FROM care_notice").fetchone()[0] == 0


def test_the_draft_has_cost_recipients_and_expected_deflection_and_no_real_phone_number(conn: sqlite3.Connection) -> None:
    draft = tools.draft_notice(conn, FLOOD, "OUTAGE", "en").data
    assert draft.recipients_est == 980 and draft.channel == "SMS"
    assert draft.cost_rm == round(980 * tools.SMS_COST_RM, 2) and draft.expected_deflection_pct == round(tools.DEFLECTION * 100)
    assert not re.search(r"\d{6,}", draft.message) and "not a real number" in draft.message
    restored = tools.draft_notice(conn, FLOOD, "RESTORED", "en").data
    assert restored.expected_deflection_pct == 0 and "back" in restored.message


def test_the_draft_checks_its_inputs(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.draft_notice(conn, FLOOD, "WEATHER", "en")
    with pytest.raises(InvalidInputError):
        tools.draft_notice(conn, FLOOD, "OUTAGE", "fr")
    with pytest.raises(InvalidInputError):
        tools.draft_notice(conn, [], "OUTAGE", "en")
    with pytest.raises(NotFoundError):
        tools.draft_notice(conn, ["ZZZZ-9999"], "OUTAGE", "en")


def test_send_needs_a_comms_send_notice_token_for_those_towers(conn: sqlite3.Connection) -> None:
    for bad in ("not-a-token", token(FLOOD, action="drone_dispatch"), token(["KKRI-0143"])):
        with pytest.raises(TokenError):
            tools.send_notice(conn, FLOOD, "en", MESSAGE, bad, "x")


def test_send_writes_a_notice_with_an_id_and_the_deflection(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    env = tools.send_notice(conn, FLOOD, "en", MESSAGE, token(FLOOD), "flood")
    notice = env.data
    assert notice.notice_id == "NTC-0001" and notice.recipients_est == 980 and notice.approved_by == "human:test"
    assert notice.tickets_deflected_est == round(980 * tools.EXTRA_TICKET_RATE["FLOOD"] * tools.DEFLECTION)
    assert conn.execute("SELECT COUNT(*) FROM care_notice").fetchone()[0] == 1


def test_send_validates_message_length_and_an_empty_audience(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.send_notice(conn, FLOOD, "en", "too short", token(FLOOD), "x")
    with pytest.raises(InvalidInputError):
        tools.send_notice(conn, FLOOD, "en", "x" * 481, token(FLOOD), "x")
    with pytest.raises(InvalidInputError):
        tools.send_notice(conn, ["KKRI-0143"], "en", MESSAGE, token(["KKRI-0143"]), "x")  # a healthy tower: nobody to tell
    with pytest.raises(InvalidInputError):
        tools.send_notice(conn, FLOOD, "xx", MESSAGE, token(FLOOD), "x")


def test_the_same_message_to_the_same_towers_within_30_minutes_is_invalid_input(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tools.send_notice(conn, FLOOD, "en", MESSAGE, token(FLOOD), "first")
    with pytest.raises(InvalidInputError):
        tools.send_notice(conn, FLOOD, "en", MESSAGE, token(FLOOD), "again")
    set_clock(12 + tools.DEDUPE_MIN + 1)
    assert tools.send_notice(conn, FLOOD, "en", MESSAGE, token(FLOOD), "later").data.notice_id == "NTC-0002"


def test_after_a_notice_the_predicted_extra_tickets_fall(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    before = tools.get_impact(conn, FLOOD).data
    tools.send_notice(conn, FLOOD, "en", MESSAGE, token(FLOOD), "x")
    after = tools.get_impact(conn, FLOOD).data
    assert after.predicted_extra_tickets_1h < before.predicted_extra_tickets_1h
    assert after.predicted_extra_tickets_if_silent == before.predicted_extra_tickets_if_silent
    assert after.notices_sent == 1 and after.notified_customers == 980


def test_list_notices_newest_first_and_has_counts_only(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tools.send_notice(conn, FLOOD, "en", MESSAGE, token(FLOOD), "one")
    set_clock(60)
    tools.send_notice(conn, FLOOD, "ms", MESSAGE.replace("Dear customer", "Pelanggan"), token(FLOOD), "two")
    listed = tools.list_notices(conn)
    assert [n.notice_id for n in listed.data.notices] == ["NTC-0002", "NTC-0001"]
    text = json.dumps(listed.model_dump(mode="json")).lower()
    assert "msisdn" not in text and "recipients\"" not in text and "customer_ref" not in text
    with pytest.raises(InvalidInputError):
        tools.list_notices(conn, limit=0)


def test_every_answer_is_synthetic_and_has_evidence(conn: sqlite3.Connection) -> None:
    for env in (tools.get_impact(conn, FLOOD), tools.draft_notice(conn, FLOOD), tools.list_notices(conn)):
        assert env.synthetic is True and env.evidence
