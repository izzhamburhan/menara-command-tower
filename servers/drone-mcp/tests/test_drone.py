from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable

import pytest
from drone_mcp import tools
from menara_core.errors import InvalidInputError, NotFoundError, TokenError

Token = Callable[..., str]


def _dispatch(conn: sqlite3.Connection, token: Token, tower: str = "KKRI-0142") -> str:
    return tools.dispatch(conn, tower, token(tower), reason="Check the access road").data.mission_id


# ---------- dispatch ----------


def test_the_nearest_idle_drone_flies_from_kota_bharu(conn: sqlite3.Connection, token: Token) -> None:
    env = tools.dispatch(conn, "KKRI-0142", token("KKRI-0142", approved_by="human:izzham"), reason="Check the road")
    m = env.data
    assert env.synthetic is True and env.warnings
    assert m.drone_id == "DRN-01" and "Kota Bharu" in m.depot_name
    assert m.status == "EN_ROUTE" and m.progress_pct == 0 and m.findings is None
    assert 60 < m.distance_km < 75
    assert m.approved_by == "human:izzham" and m.reason == "Check the road"
    assert m.arrives_at.startswith("2026-11-14T07:4") and m.completes_at > m.arrives_at
    assert env.evidence[0].tool == "drone_dispatch" and env.evidence[0].ref == m.mission_id


def test_flight_time_follows_distance_and_speed(conn: sqlite3.Connection, token: Token) -> None:
    mission = tools.dispatch(conn, "KKRI-0142", token("KKRI-0142")).data
    row = conn.execute("SELECT eta_min, distance_km FROM drone_mission WHERE mission_id = ?", (mission.mission_id,)).fetchone()
    assert row["eta_min"] == math.ceil(row["distance_km"] / 90 * 60)


def test_the_mission_progresses_with_the_clock_and_findings_appear_at_the_end(
    conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]
) -> None:
    mission_id = _dispatch(conn, token)
    set_clock(20)
    en_route = tools.get_mission(conn, mission_id)
    assert en_route.data.status == "EN_ROUTE" and 0 < en_route.data.progress_pct < 100 and en_route.warnings
    set_clock(50)
    assert tools.get_mission(conn, mission_id).data.status == "ON_SITE"
    set_clock(70)
    done = tools.get_mission(conn, mission_id).data
    assert done.status == "COMPLETE" and done.findings is not None
    f = done.findings
    assert f.vision_model == "synthetic-canned"
    assert f.access_road.status == "FLOODED" and f.access_road.water_depth_m == 0.6 and f.access_road.passable_by == "BOAT"
    assert f.tower_structure == "INTACT" and f.antenna_alignment == "ALIGNED"
    assert f.genset.status == "UNREACHABLE_BY_ROAD" and f.hazards
    assert "0.6 m" in f.summary and f.confidence == 0.91


def test_a_normal_site_has_normal_findings(conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]) -> None:
    tower = conn.execute("SELECT enodeb_name FROM tower WHERE enodeb_name LIKE 'KULP-%' ORDER BY enodeb_name").fetchone()[0]
    mission_id = _dispatch(conn, token, tower)
    set_clock(240)
    f = tools.get_mission(conn, mission_id).data.findings
    assert f is not None and f.access_road.status == "PASSABLE" and f.hazards == []


def test_a_second_dispatch_uses_the_other_drone_and_a_third_finds_none(conn: sqlite3.Connection, token: Token) -> None:
    first = tools.dispatch(conn, "KKRI-0142", token("KKRI-0142")).data
    second = tools.dispatch(conn, "KKRI-0143", token("KKRI-0143")).data
    assert {first.drone_id, second.drone_id} == {"DRN-01", "DRN-02"}
    with pytest.raises(InvalidInputError, match="No idle drone"):
        tools.dispatch(conn, "KKRI-0144", token("KKRI-0144"))
    drones = tools.list_drones(conn).data
    assert drones.idle == 10 and {d.drone_id for d in drones.drones if d.status == "ON_MISSION"} == {"DRN-01", "DRN-02"}


def test_drones_come_home_and_can_fly_again(conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]) -> None:
    tools.dispatch(conn, "KKRI-0142", token("KKRI-0142"))
    tools.dispatch(conn, "KKRI-0143", token("KKRI-0143"))
    set_clock(240)
    assert tools.list_drones(conn).data.idle == 12
    assert tools.dispatch(conn, "KKRI-0144", token("KKRI-0144")).data.status == "EN_ROUTE"


def test_one_active_mission_per_tower(conn: sqlite3.Connection, token: Token) -> None:
    first = _dispatch(conn, token)
    with pytest.raises(InvalidInputError, match=first):
        tools.dispatch(conn, "KKRI-0142", token("KKRI-0142"))


def test_a_tower_beyond_every_depot_cannot_be_reached(conn: sqlite3.Connection, token: Token) -> None:
    far = conn.execute("SELECT enodeb_name FROM tower WHERE enodeb_name LIKE 'SDKN-%' ORDER BY enodeb_name").fetchone()[0]
    with pytest.raises(InvalidInputError, match="No idle drone within 150 km"):
        tools.dispatch(conn, far, token(far))


# ---------- tokens and validation ----------


def test_a_bad_token_dispatches_nothing(conn: sqlite3.Connection, token: Token) -> None:
    with pytest.raises(TokenError, match="signature"):
        tools.dispatch(conn, "KKRI-0142", "forged.token")
    with pytest.raises(TokenError, match="different"):
        tools.dispatch(conn, "KKRI-0142", token("KKRI-0143"))  # wrong tower
    with pytest.raises(TokenError, match="different"):
        tools.dispatch(conn, "KKRI-0142", token("KKRI-0142", action="ran_tilt_cells"))  # wrong action
    assert tools.list_missions(conn).data.returned == 0


def test_input_validation(conn: sqlite3.Connection, token: Token) -> None:
    with pytest.raises(InvalidInputError):
        tools.dispatch(conn, "nope", "x")
    with pytest.raises(NotFoundError):
        tools.dispatch(conn, "ZZZZ-9999", token("ZZZZ-9999"))
    with pytest.raises(InvalidInputError):
        tools.get_mission(conn, "1")
    with pytest.raises(NotFoundError):
        tools.get_mission(conn, "MIS-9999")
    with pytest.raises(InvalidInputError):
        tools.list_missions(conn, status="LOST")
    with pytest.raises(InvalidInputError):
        tools.list_missions(conn, limit=0)


# ---------- listing and ownership ----------


def test_list_missions_filters(conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]) -> None:
    first = _dispatch(conn, token)
    assert [m.mission_id for m in tools.list_missions(conn).data.missions] == [first]
    assert tools.list_missions(conn, status="COMPLETE").data.returned == 0
    assert tools.list_missions(conn, enodeb_name="KKRI-0143").data.returned == 0
    set_clock(70)
    assert [m.mission_id for m in tools.list_missions(conn, status="COMPLETE").data.missions] == [first]


def test_a_mission_dispatched_in_the_future_is_not_visible_yet(
    conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]
) -> None:
    set_clock(30)
    mission_id = _dispatch(conn, token)
    set_clock(0)
    with pytest.raises(NotFoundError, match="current scenario time"):
        tools.get_mission(conn, mission_id)
    assert tools.list_missions(conn).data.returned == 0


def test_drone_cannot_write_other_tables(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("UPDATE drone_finding SET finding = '{}'")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("DELETE FROM drone")
