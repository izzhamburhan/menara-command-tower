"""events-mcp tools: crowd events ahead, and the load they will put on nearby towers. Fictional events, invented numbers."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from events_mcp import tools
from menara_core.errors import InvalidInputError, NotFoundError


def derby(conn: sqlite3.Connection) -> str:
    return str(conn.execute("SELECT event_id FROM crowd_event WHERE name LIKE 'Kota Bharu Derby%'").fetchone()[0])


def test_events_are_listed_by_circle_and_window_soonest_first(conn: sqlite3.Connection) -> None:
    data = tools.list_upcoming(conn, 4.2, 108.0, 100.0, 5760).data  # a huge window in the middle of the peninsula and Borneo
    starts = [e.starts_in_min for e in data.events]
    assert starts == sorted(starts) and data.returned == len(data.events)
    everything = tools.list_upcoming(conn, 4.2, 108.0, 100.0, 14400)
    assert everything.synthetic is True and everything.evidence[0].tool == "events_list_upcoming"


def test_a_circle_and_a_short_window_narrow_the_list(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT lat, lng FROM crowd_event WHERE event_id = ?", (derby(conn),)).fetchone()
    near = tools.list_upcoming(conn, row["lat"], row["lng"], 5.0, 14400).data
    assert derby(conn) in {e.event_id for e in near.events}
    assert all(e.distance_km <= 5.0 for e in near.events) and all(len(e.serving_towers) == 5 for e in near.events)
    soon = tools.list_upcoming(conn, row["lat"], row["lng"], 5.0, 60).data
    assert derby(conn) not in {e.event_id for e in soon.events}


def test_an_event_in_the_past_is_not_listed_and_an_ongoing_one_is_marked(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    row = conn.execute("SELECT lat, lng, start_min, end_min FROM crowd_event WHERE event_id = ?", (derby(conn),)).fetchone()
    set_clock(row["start_min"] + 30)
    during = {e.event_id: e for e in tools.list_upcoming(conn, row["lat"], row["lng"], 5.0, 600).data.events}
    assert during[derby(conn)].status == "ONGOING"
    set_clock(row["end_min"] + 10)
    assert derby(conn) not in {e.event_id for e in tools.list_upcoming(conn, row["lat"], row["lng"], 5.0, 600).data.events}


def test_forecast_adds_load_to_the_nearest_towers_and_labels_the_risk(conn: sqlite3.Connection) -> None:
    env = tools.forecast_load(conn, derby(conn))
    data = env.data
    assert len(data.towers) == 5 and data.attendance >= 30000
    for t in data.towers:
        assert t.predicted_prb == min(100.0, round(t.baseline_prb + t.uplift_prb, 1))
        assert t.risk == ("HIGH" if t.predicted_prb >= 85 else "MEDIUM" if t.predicted_prb >= 70 else "LOW")
        assert t.subscribers_est > 0
    assert data.overall_risk in {"MEDIUM", "HIGH"} and data.subscribers_affected == sum(t.subscribers_est for t in data.towers)
    assert abs(sum(t.uplift_prb for t in data.towers) - data.attendance * 0.004) < 0.6


def test_a_bigger_crowd_gives_a_higher_risk(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT event_id, attendance FROM crowd_event ORDER BY attendance").fetchall()
    small = tools.forecast_load(conn, rows[0]["event_id"]).data
    big = tools.forecast_load(conn, rows[-1]["event_id"]).data
    assert max(t.uplift_prb for t in big.towers) > max(t.uplift_prb for t in small.towers)


def test_the_capacity_plan_names_towers_the_exposure_profile_and_the_next_tool(conn: sqlite3.Connection) -> None:
    plan = tools.capacity_plan(conn, derby(conn)).data
    assert plan.event_id == derby(conn) and plan.recommendations
    tools_named = {r.next_tool for r in plan.recommendations}
    assert {"exposure_quote", "care_draft_notice"} <= tools_named and "twin_simulate_tilt" in tools_named
    assert all(r.towers and r.advice and r.priority in {1, 2, 3} for r in plan.recommendations)
    assert plan.recommendations[0].priority == min(r.priority for r in plan.recommendations)
    assert plan.note and "nothing is executed" in plan.note.lower()


def test_an_unknown_event_is_not_found_and_bad_ranges_are_invalid(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        tools.forecast_load(conn, "EVT-999")
    with pytest.raises(NotFoundError):
        tools.capacity_plan(conn, "EVT-999")
    for kwargs in ({"radius_km": 0.0}, {"radius_km": 101.0}, {"within_min": 4}, {"within_min": 14401}, {"lat": 91.0}):
        args: dict[str, float] = {"lat": 4.0, "lng": 100.0, "radius_km": 10.0, "within_min": 600}
        args.update(kwargs)
        with pytest.raises(InvalidInputError):
            tools.list_upcoming(conn, **args)  # type: ignore[arg-type]
