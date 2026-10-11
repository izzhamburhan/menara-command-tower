"""field-mcp tools: which technician to send (road or boat), parts, safety, and dispatching them. Fictional crew."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from field_mcp import tools
from menara_core import settings
from menara_core.errors import InvalidInputError, NotFoundError, TokenError
from menara_core.ids import target_key
from menara_core.tokens import issue_token

FLOOD_TOWER = "KKRI-0142"


def token(tower: str, action: str = "workforce_create_order") -> str:
    return issue_token(settings.signing_key(), action=action, target=target_key([tower]), approved_by="human:test")


def a_dry_tower(conn: sqlite3.Connection) -> str:
    return str(conn.execute("SELECT enodeb_name FROM tower WHERE enodeb_name LIKE 'KTBH-%' ORDER BY enodeb_name LIMIT 1").fetchone()[0])


def test_crew_are_ranked_by_eta_and_must_have_the_skill_and_be_on_shift(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)  # 07:12: the 06:00-18:00 shift is on
    data = tools.find_crew(conn, a_dry_tower(conn), "POWER").data
    assert data.candidates and [c.eta_min for c in data.candidates] == sorted(c.eta_min for c in data.candidates)
    for c in data.candidates:
        row = conn.execute("SELECT skills, shift_start_hour, shift_end_hour FROM technician WHERE tech_id = ?", (c.tech_id,)).fetchone()
        assert "POWER" in row["skills"].split(",") and tools.on_shift(7, row["shift_start_hour"], row["shift_end_hour"])
    assert data.candidates[0].depot_id == "DEP-KTBH"  # the nearest depot to Kota Bharu


def test_nobody_is_listed_outside_their_shift(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12 + 8 * 60)  # 15:12: the 08:00-20:00 and the 06:00-18:00 shifts; the 18:00-06:00 night shift is off
    shifts = {
        conn.execute("SELECT shift_start_hour, shift_end_hour FROM technician WHERE tech_id = ?", (c.tech_id,)).fetchone()["shift_start_hour"]
        for c in tools.find_crew(conn, a_dry_tower(conn), "POWER").data.candidates
    }
    assert shifts and 18 not in shifts


def test_a_tower_in_the_flood_extent_gets_boat_access_with_extra_time_and_a_safety_note(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    env = tools.find_crew(conn, FLOOD_TOWER, "POWER")
    data = env.data
    assert data.access == "BOAT" and data.flood_depth_m >= tools.BOAT_DEPTH_M and "boat" in data.safety_note.lower()
    assert all(c.access == "BOAT" for c in data.candidates)
    dry = tools.find_crew(conn, a_dry_tower(conn), "POWER").data
    assert dry.access == "ROAD" and dry.flood_depth_m == 0 and dry.safe_to_dispatch is True
    assert data.candidates[0].eta_min >= tools.BOAT_EXTRA_MIN and env.warnings


def test_road_into_deep_water_is_not_safe_to_dispatch_but_boat_is(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    data = tools.find_crew(conn, FLOOD_TOWER, "POWER").data
    assert data.safe_to_dispatch is True  # by boat
    assert data.road_safe is False


def test_parts_for_the_skill_are_reported_per_depot(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    first = tools.find_crew(conn, a_dry_tower(conn), "POWER").data.candidates[0]
    assert {p.part for p in first.parts} <= {"GENERATOR", "RECTIFIER", "BATTERY"} and first.parts
    ran = tools.find_crew(conn, a_dry_tower(conn), "RAN").data.candidates[0]
    assert {p.part for p in ran.parts} == {"ANTENNA"}
    assert tools.find_crew(conn, a_dry_tower(conn), "FIBRE").data.candidates[0].parts == []


def test_dispatch_needs_the_workforce_create_order_token_and_writes_a_job(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tower = a_dry_tower(conn)
    tech = tools.find_crew(conn, tower, "POWER").data.candidates[0].tech_id
    for bad in ("not-a-token", token(tower, action="drone_dispatch"), token("KKRI-0143")):
        with pytest.raises(TokenError):
            tools.dispatch(conn, tower, tech, "Replace the rectifier", bad, "x")
    job = tools.dispatch(conn, tower, tech, "Replace the rectifier", token(tower), "outage").data
    assert job.job_id == "JOB-0001" and job.tech_id == tech and job.access == "ROAD" and job.eta_min > 0 and job.approved_by == "human:test"
    assert conn.execute("SELECT COUNT(*) FROM field_job").fetchone()[0] == 1


def test_dispatch_rejects_a_busy_or_off_shift_or_unskilled_technician(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tower = a_dry_tower(conn)
    crew = tools.find_crew(conn, tower, "POWER").data.candidates
    tools.dispatch(conn, tower, crew[0].tech_id, "First job", token(tower), "x")
    with pytest.raises(InvalidInputError):  # busy
        tools.dispatch(conn, tower, crew[0].tech_id, "Second job", token(tower), "x")
    night = conn.execute("SELECT tech_id FROM technician WHERE shift_start_hour = 18 AND skills LIKE '%POWER%' LIMIT 1").fetchone()
    if night is not None:
        with pytest.raises(InvalidInputError):  # off shift at 07:12
            tools.dispatch(conn, tower, night["tech_id"], "Night job", token(tower), "x")
    fibre_only = conn.execute("SELECT tech_id FROM technician WHERE skills NOT LIKE '%POWER%' AND shift_start_hour = 6 LIMIT 1").fetchone()
    with pytest.raises(InvalidInputError):  # no POWER skill
        tools.dispatch(conn, tower, fibre_only["tech_id"], "Wrong skill", token(tower), "x")
    with pytest.raises(NotFoundError):
        tools.dispatch(conn, tower, "TECH-999", "Ghost", token(tower), "x")


def test_dispatching_road_into_unsafe_water_is_invalid_input_but_boat_is_allowed(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tech = tools.find_crew(conn, FLOOD_TOWER, "POWER").data.candidates[0].tech_id
    with pytest.raises(InvalidInputError):
        tools.dispatch(conn, FLOOD_TOWER, tech, "Refuel the generator", token(FLOOD_TOWER), "x", access="ROAD")
    job = tools.dispatch(conn, FLOOD_TOWER, tech, "Refuel the generator", token(FLOOD_TOWER), "x").data  # AUTO picks the boat
    assert job.access == "BOAT"


def test_job_status_follows_the_clock_en_route_on_site_done(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tower = a_dry_tower(conn)
    tech = tools.find_crew(conn, tower, "POWER").data.candidates[0].tech_id
    job = tools.dispatch(conn, tower, tech, "Check the power cabinet", token(tower), "x").data
    assert tools.list_jobs(conn).data.jobs[0].status == "EN_ROUTE"
    set_clock(12 + job.eta_min + 5)
    assert tools.list_jobs(conn).data.jobs[0].status == "ON_SITE"
    set_clock(12 + job.eta_min + tools.WORK_MIN + 5)
    assert tools.list_jobs(conn).data.jobs[0].status == "DONE"


def test_list_jobs_filters_by_status_and_validates(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    tower = a_dry_tower(conn)
    tech = tools.find_crew(conn, tower, "POWER").data.candidates[0].tech_id
    tools.dispatch(conn, tower, tech, "Check the power cabinet", token(tower), "x")
    assert tools.list_jobs(conn, status="EN_ROUTE").data.returned == 1 and tools.list_jobs(conn, status="DONE").data.returned == 0
    with pytest.raises(InvalidInputError):
        tools.list_jobs(conn, status="MAYBE")
    with pytest.raises(InvalidInputError):
        tools.list_jobs(conn, limit=0)


def test_input_validation(conn: sqlite3.Connection) -> None:
    tower = a_dry_tower(conn)
    with pytest.raises(InvalidInputError):
        tools.find_crew(conn, tower, "WELDING")
    with pytest.raises(NotFoundError):
        tools.find_crew(conn, "ZZZZ-9999", "POWER")
    with pytest.raises(InvalidInputError):
        tools.dispatch(conn, tower, "TECH-001", "ab", token(tower), "x")  # task too short
