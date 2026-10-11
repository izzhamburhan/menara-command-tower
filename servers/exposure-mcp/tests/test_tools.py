"""exposure-mcp tools: selling network quality as a product. A quote from the spare capacity, and a booking."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from exposure_mcp import tools
from menara_core import settings
from menara_core.errors import InvalidInputError, NotFoundError, TokenError
from menara_core.ids import target_key
from menara_core.tokens import issue_token

PROFILE = "BROADCAST_UPLINK"


def token(names: list[str], action: str = "exposure_book_qod") -> str:
    return issue_token(settings.signing_key(), action=action, target=target_key(names), approved_by="human:test")


def a_quiet_tower(conn: sqlite3.Connection, other: bool = False) -> str:
    """A tower that is up with plenty of spare capacity now and no event nearby."""
    event_towers = {
        r["enodeb_name"]
        for e in conn.execute("SELECT lat, lng FROM crowd_event")
        for r in conn.execute("SELECT enodeb_name, lat, lng FROM tower")
        if abs(r["lat"] - e["lat"]) < 0.08 and abs(r["lng"] - e["lng"]) < 0.08
    }
    rows = conn.execute(
        "SELECT t.enodeb_name FROM tower t JOIN tower_kpi k ON k.enodeb_name = t.enodeb_name AND k.t_min = "
        "(SELECT MAX(t_min) FROM tower_kpi WHERE enodeb_name = t.enodeb_name AND t_min <= 0) "
        "WHERE t.enodeb_name NOT LIKE 'KKRI-%' AND k.prb_util < 40 ORDER BY t.enodeb_name"
    ).fetchall()
    names = [r["enodeb_name"] for r in rows if r["enodeb_name"] not in event_towers]
    assert len(names) >= 2, "the test database has too few quiet towers"
    return names[1] if other else names[0]


def test_four_profiles_with_prices_and_headroom_needs(conn: sqlite3.Connection) -> None:
    env = tools.list_profiles(conn)
    assert [p.profile_id for p in env.data.profiles] == ["AR_EXPERIENCE", "BROADCAST_UPLINK", "ESPORTS_LOW_LATENCY", "FLEET_TELEMATICS"]
    assert all(p.price_rm_per_hour_per_tower > 0 and p.headroom_prb > 0 for p in env.data.profiles) and env.synthetic is True


def test_a_quiet_tower_is_feasible_and_the_quote_adds_up(conn: sqlite3.Connection) -> None:
    tower = a_quiet_tower(conn)
    data = tools.quote(conn, PROFILE, [tower], 120).data
    assert data.all_feasible is True and data.towers[0].feasible is True and data.towers[0].reason == ""
    profile = conn.execute("SELECT * FROM qod_profile WHERE profile_id = ?", (PROFILE,)).fetchone()
    assert data.price_rm == round(2.0 * profile["price_rm_per_hour_per_tower"], 2)
    assert data.reserved_prb_per_tower == profile["headroom_prb"] and data.feasible_towers == [tower]


def test_an_overloaded_tower_is_not_feasible_with_the_reason(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)  # the flood neighbours are at 91% PRB
    data = tools.quote(conn, PROFILE, ["KKRI-0143"], 60).data
    assert data.all_feasible is False and data.towers[0].feasible is False and "spare capacity" in data.towers[0].reason
    assert data.price_rm == 0 and data.feasible_towers == []


def test_a_down_tower_is_not_feasible(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    data = tools.quote(conn, "FLEET_TELEMATICS", ["KKRI-0142"], 60).data
    assert data.towers[0].feasible is False and "not up" in data.towers[0].reason


def test_inputs_are_validated(conn: sqlite3.Connection) -> None:
    tower = a_quiet_tower(conn)
    for kwargs in ({"duration_min": 14}, {"duration_min": 721}, {"start_in_min": -1}, {"start_in_min": 4321}):
        args = {"duration_min": 60, "start_in_min": 0}
        args.update(kwargs)
        with pytest.raises(InvalidInputError):
            tools.quote(conn, PROFILE, [tower], **args)
    with pytest.raises(InvalidInputError):
        tools.quote(conn, PROFILE, [], 60)
    with pytest.raises(NotFoundError):
        tools.quote(conn, "NOPE", [tower], 60)
    with pytest.raises(NotFoundError):
        tools.quote(conn, PROFILE, ["ZZZZ-9999"], 60)


def test_book_needs_the_exposure_book_qod_token_and_writes_a_booking(conn: sqlite3.Connection) -> None:
    tower = a_quiet_tower(conn)
    for bad in ("not-a-token", token([tower], action="comms_send_notice"), token(["KKRI-0143"])):
        with pytest.raises(TokenError):
            tools.book(conn, PROFILE, [tower], 60, "Fictional Media Crew", bad, "x")
    booking = tools.book(conn, PROFILE, [tower], 60, "Fictional Media Crew", token([tower]), "derby").data
    assert booking.booking_id == "BKG-0001" and booking.customer == "Fictional Media Crew" and booking.to_min - booking.from_min == 60
    assert booking.price_rm == tools.quote(conn, PROFILE, [tower], 60).data.price_rm or booking.price_rm > 0
    assert conn.execute("SELECT COUNT(*) FROM qod_booking").fetchone()[0] == 1


def test_booking_an_infeasible_tower_or_a_bad_customer_name_is_invalid_input(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    with pytest.raises(InvalidInputError):
        tools.book(conn, PROFILE, ["KKRI-0143"], 60, "Fictional Media Crew", token(["KKRI-0143"]), "x")
    tower = a_quiet_tower(conn)
    for name in ("ab", "x" * 61, "  "):
        with pytest.raises(InvalidInputError):
            tools.book(conn, PROFILE, [tower], 60, name, token([tower]), "x")


def test_reserved_headroom_shows_in_the_next_quote_for_the_same_window(conn: sqlite3.Connection) -> None:
    tower = a_quiet_tower(conn)
    before = tools.quote(conn, "AR_EXPERIENCE", [tower], 60).data.towers[0]
    tools.book(conn, "AR_EXPERIENCE", [tower], 60, "Fictional Venue Ltd", token([tower]), "x")
    after = tools.quote(conn, "AR_EXPERIENCE", [tower], 60).data.towers[0]
    assert after.reserved_prb == before.reserved_prb + 15.0
    assert after.headroom_available_prb == pytest.approx(before.headroom_available_prb - 15.0)
    later = tools.quote(conn, "AR_EXPERIENCE", [tower], 60, start_in_min=180).data.towers[0]  # after the booking ended
    assert later.reserved_prb == before.reserved_prb


def test_the_quote_includes_event_uplift_when_an_event_is_present(conn: sqlite3.Connection) -> None:
    event = conn.execute("SELECT * FROM crowd_event WHERE name LIKE 'Kota Bharu Derby%'").fetchone()
    from menara_core.crowd import serving_towers

    nearest = serving_towers(conn, event["lat"], event["lng"], 1)[0][0]
    quiet = tools.quote(conn, PROFILE, [nearest], 60, start_in_min=0).data.towers[0]
    on_the_day = tools.quote(conn, PROFILE, [nearest], 60, start_in_min=event["start_min"] + 30).data.towers[0]
    assert quiet.event_uplift_prb == 0 and on_the_day.event_uplift_prb > 20
    assert on_the_day.headroom_available_prb < quiet.headroom_available_prb


def test_every_answer_is_synthetic_and_has_evidence(conn: sqlite3.Connection) -> None:
    tower = a_quiet_tower(conn)
    for env in (tools.list_profiles(conn), tools.quote(conn, PROFILE, [tower], 60)):
        assert env.synthetic is True and env.evidence
