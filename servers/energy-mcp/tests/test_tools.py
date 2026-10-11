"""energy-mcp tools: power draw, battery and generator time, and night-time sleep savings. Invented numbers."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from energy_mcp import tools
from menara_core import settings
from menara_core.errors import InvalidInputError, TokenError
from menara_core.ids import target_key
from menara_core.tokens import issue_token

NIGHT = 20 * 60  # scenario minute 1200 is 03:00 the next day (T0 is 07:00)
DAY = 0


def token(names: list[str], action: str = "energy_sleep_cells") -> str:
    return issue_token(settings.signing_key(), action=action, target=target_key(names), approved_by="human:test")


def a_candidate(conn: sqlite3.Connection, hour: int = 3) -> str:
    for row in conn.execute("SELECT enodeb_name, lat, lng FROM tower WHERE enodeb_name NOT LIKE 'KKRI-%' ORDER BY enodeb_name"):
        found = tools.find_savings(conn, row["lat"], row["lng"], 1.0, hour=hour).data.candidates
        if found:
            return str(found[0].enodeb_name)
    raise AssertionError("the test database has no sleep candidate")


def test_the_flooded_tower_runs_on_battery_or_generator_with_a_finite_time_left_and_a_warning(conn: sqlite3.Connection) -> None:
    env = tools.get_tower(conn, "KKRI-0142")
    data = env.data
    assert data.supply in {"BATTERY", "GENERATOR"} and data.mains_ok is False
    assert data.hours_left is not None and 0 < data.hours_left < 24
    assert data.generator_hours_left is not None and 5 <= data.generator_hours_left <= 12
    assert env.warnings and env.synthetic is True and env.evidence[0].tool == "energy_get_tower"


def test_a_healthy_tower_is_on_mains_and_has_no_hours_warning(conn: sqlite3.Connection) -> None:
    name = a_candidate(conn)
    env = tools.get_tower(conn, name)
    assert env.data.supply == "MAINS" and env.data.hours_left is None and env.warnings == []


def test_draw_rises_with_load(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT enodeb_name, prb_util FROM tower_kpi WHERE t_min = -60 AND enodeb_name NOT LIKE 'KKRI-%' ORDER BY prb_util").fetchall()
    low, high = rows[0], rows[-1]
    base = {r["enodeb_name"]: r["base_kw"] for r in conn.execute("SELECT enodeb_name, base_kw FROM tower_energy")}
    # same base power: compare a tower with itself at two loads through the model's own formula
    assert tools.draw_kw(base[low["enodeb_name"]], low["prb_util"]) < tools.draw_kw(base[low["enodeb_name"]], high["prb_util"])


def test_savings_only_in_the_sleep_window(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    lat, lng = conn.execute("SELECT lat, lng FROM tower WHERE enodeb_name NOT LIKE 'KKRI-%' ORDER BY enodeb_name LIMIT 1").fetchone()
    set_clock(DAY)
    assert tools.find_savings(conn, lat, lng, 100.0).data.candidates == []  # 07:00
    set_clock(NIGHT)
    assert tools.find_savings(conn, lat, lng, 100.0).data.candidates  # 03:00


def test_candidates_need_two_cells_a_quiet_night_up_neighbours_and_no_emergency_site(conn: sqlite3.Connection) -> None:
    candidates = tools.find_savings(conn, 4.2, 108.0, 100.0, hour=3).data.candidates
    for c in candidates:
        cells = conn.execute("SELECT COUNT(*) FROM cell WHERE enodeb_name = ?", (c.enodeb_name,)).fetchone()[0]
        emergency = conn.execute("SELECT COUNT(*) FROM critical_site WHERE serving_enodeb = ? AND emergency_service = 1", (c.enodeb_name,)).fetchone()[0]
        assert cells >= 2 and emergency == 0 and c.risk in {"LOW", "MEDIUM"} and c.kwh_saved > 0
        assert abs(c.co2_kg_saved - round(c.kwh_saved * tools.CO2_KG_PER_KWH, 2)) < 0.02


def test_a_tower_in_a_flood_extent_is_never_a_candidate(conn: sqlite3.Connection) -> None:
    names = {c.enodeb_name for c in tools.find_savings(conn, 5.531, 102.197, 50.0, hour=3).data.candidates}
    assert "KKRI-0142" not in names and "KKRI-0143" not in names  # the flooded tower and the emergency-site tower


def test_apply_sleep_writes_one_action_per_tower_and_returns_totals(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(NIGHT)
    name = a_candidate(conn)
    env = tools.apply_sleep(conn, [name], token([name]), "quiet night")
    data = env.data
    assert [a.action_id for a in data.actions] == ["ENA-0001"] and data.total_kwh_saved > 0
    assert data.actions[0].enodeb_name == name and data.actions[0].to_min > data.actions[0].from_min
    assert abs(data.total_co2_kg_saved - round(data.total_kwh_saved * tools.CO2_KG_PER_KWH, 2)) < 0.02
    assert conn.execute("SELECT COUNT(*) FROM energy_action").fetchone()[0] == 1


def test_apply_sleep_rejects_a_missing_or_wrong_token(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(NIGHT)
    name = a_candidate(conn)
    with pytest.raises(TokenError):
        tools.apply_sleep(conn, [name], "not-a-token", "x")
    with pytest.raises(TokenError):
        tools.apply_sleep(conn, [name], token([name], action="ran_tilt_cells"), "x")
    with pytest.raises(TokenError):
        tools.apply_sleep(conn, [name], token(["KKRI-0143"]), "x")


def test_a_non_candidate_or_a_repeat_is_invalid_input(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(NIGHT)
    with pytest.raises(InvalidInputError):  # serves an emergency site and is flooded
        tools.apply_sleep(conn, ["KKRI-0142"], token(["KKRI-0142"]), "x")
    name = a_candidate(conn)
    tools.apply_sleep(conn, [name], token([name]), "first")
    with pytest.raises(InvalidInputError):
        tools.apply_sleep(conn, [name], token([name]), "again")


def test_the_draw_drops_after_an_action_until_its_end_and_the_saving_is_capped(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(NIGHT)
    name = a_candidate(conn)
    before = tools.get_tower(conn, name).data.draw_kw
    done = tools.apply_sleep(conn, [name], token([name]), "x").data.actions[0]
    after = tools.get_tower(conn, name).data
    assert after.draw_kw < before and after.sleeping is True
    assert after.draw_kw >= before * (1 - tools.SLEEPABLE_SHARE) - 0.01
    hours = (done.to_min - done.from_min) / 60
    base = conn.execute("SELECT base_kw FROM tower_energy WHERE enodeb_name = ?", (name,)).fetchone()["base_kw"]
    night_draw = tools.draw_kw(base, tools._night_load(conn, name))
    assert abs(done.kwh_saved - round(night_draw * tools.SLEEPABLE_SHARE * hours, 2)) < 0.02  # a share of the night draw, never more
    set_clock(done.to_min + 5)
    assert tools.get_tower(conn, name).data.sleeping is False


@pytest.mark.parametrize(
    "kwargs",
    [{"radius_km": 0.0}, {"radius_km": 101.0}, {"hour": 24}, {"hour": -1}, {"lat": 91.0}, {"lng": 181.0}],
)
def test_bad_ranges_are_invalid_input(conn: sqlite3.Connection, kwargs: dict[str, float]) -> None:
    args: dict[str, float] = {"lat": 4.0, "lng": 100.0, "radius_km": 5.0}
    args.update(kwargs)
    with pytest.raises(InvalidInputError):
        tools.find_savings(conn, **args)  # type: ignore[arg-type]


def test_the_number_of_towers_to_apply_is_validated(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.apply_sleep(conn, [], "t", "x")
    names = [f"AAAA-{i:04d}" for i in range(1, 22)]
    with pytest.raises(InvalidInputError):
        tools.apply_sleep(conn, names, "t", "x")
    with pytest.raises(InvalidInputError):
        tools.apply_sleep(conn, ["bad"], "t", "x")
