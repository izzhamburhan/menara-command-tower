from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from twin_mcp import tools


def _tilt(*pairs: tuple[str, float]) -> list[dict[str, object]]:
    return [{"enodeb_name": name, "tilt_delta_deg": delta} for name, delta in pairs]


# ---------- tilt ----------


def test_tilting_the_overloaded_neighbours_takes_91_to_63(conn: sqlite3.Connection) -> None:
    env = tools.simulate_tilt(conn, _tilt(("KKRI-0143", 4.0), ("KKRI-0144", 4.0)))
    data = env.data
    assert env.synthetic is True and data.sim_id.startswith("SIM-")
    assert [(t.enodeb_name, t.current_prb, t.predicted_prb) for t in data.tilted] == [
        ("KKRI-0143", 91.0, 63.0),
        ("KKRI-0144", 91.0, 63.0),
    ]
    assert all(t.change_points == -28.0 and not t.overloaded for t in data.tilted)
    assert data.coverage_loss_pct == {"KKRI-0143": 14.0, "KKRI-0144": 14.0}
    assert data.recommended is True and all(not r.overloaded for r in data.receivers)
    assert "KKRI-0142" not in {r.enodeb_name for r in data.receivers}  # DOWN towers absorb nothing
    assert env.evidence[0].tool == "twin_simulate_tilt" and env.evidence[0].ref == data.sim_id


def test_a_big_tilt_is_not_recommended_because_it_loses_coverage(conn: sqlite3.Connection) -> None:
    data = tools.simulate_tilt(conn, _tilt(("KKRI-0143", 6.0))).data
    assert data.tilted[0].predicted_prb == 54.6  # the reduction is capped at 40 %
    assert data.recommended is False
    assert any("coverage loss 21%" in r for r in data.reasons)


def test_a_small_tilt_leaves_the_tower_overloaded(conn: sqlite3.Connection) -> None:
    data = tools.simulate_tilt(conn, _tilt(("KKRI-0143", 0.5))).data
    assert data.tilted[0].overloaded is True and data.recommended is False
    assert any("still overloaded" in r for r in data.reasons)


def test_an_uptilt_adds_load(conn: sqlite3.Connection) -> None:
    tower = tools.simulate_tilt(conn, _tilt(("KKRI-0143", -2.0))).data.tilted[0]
    assert tower.predicted_prb == 100.0 and tower.overloaded is True
    assert tools.simulate_tilt(conn, _tilt(("KKRI-0145", -1.0))).data.coverage_loss_pct == {"KKRI-0145": 0.0}


def test_tilting_a_down_tower_changes_nothing(conn: sqlite3.Connection) -> None:
    data = tools.simulate_tilt(conn, _tilt(("KKRI-0142", 4.0))).data
    assert data.tilted[0].predicted_prb == 0.0 and data.recommended is False
    assert any("is DOWN" in r for r in data.reasons)


def test_tilt_validation(conn: sqlite3.Connection) -> None:
    for bad in (
        [],
        _tilt(("KKRI-0143", 9.0)),
        _tilt(("KKRI-0143", 1.0), ("KKRI-0143", 2.0)),
        _tilt(*[("KKRI-0143", 1.0)] * 21),
        [{"enodeb_name": "KKRI-0143"}],
        [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": "lots"}],
        _tilt(("kkri", 1.0)),
    ):
        with pytest.raises(InvalidInputError):
            tools.simulate_tilt(conn, bad)
    with pytest.raises(NotFoundError):
        tools.simulate_tilt(conn, _tilt(("ZZZZ-9999", 1.0)))


def test_before_the_incident_loads_are_normal(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    tower = tools.simulate_tilt(conn, _tilt(("KKRI-0143", 4.0))).data.tilted[0]
    assert tower.current_prb is not None and tower.current_prb < 80


# ---------- failure ----------


def test_failure_of_a_tower_that_is_already_down(conn: sqlite3.Connection) -> None:
    env = tools.simulate_failure(conn, "KKRI-0142")
    d = env.data
    assert d.already_down is True and env.warnings
    assert d.subscribers_impacted == 980 and d.emergency_sites_affected == 2
    assert set(d.critical_sites_affected) == {"CS-KKRI-01", "CS-KKRI-03"}
    assert all(n.predicted_prb == n.current_prb for n in d.neighbours)
    assert {n.enodeb_name for n in d.neighbours if n.overloaded} >= {"KKRI-0143", "KKRI-0144"}
    assert "already DOWN" in d.recommendation


def test_failure_of_a_healthy_tower_shifts_load_to_its_live_neighbours(conn: sqlite3.Connection) -> None:
    d = tools.simulate_failure(conn, "SITE-KKRI-0143").data
    assert d.already_down is False and d.origin == "KKRI-0143" and d.load_before_prb == 91.0
    by_name = {n.enodeb_name: n for n in d.neighbours}
    assert by_name["KKRI-0142"].status == "DOWN" and by_name["KKRI-0142"].predicted_prb == by_name["KKRI-0142"].current_prb
    live = [n for n in d.neighbours if n.status != "DOWN"]
    assert live and all((n.change_points or 0) > 0 for n in live)
    assert d.overloaded_count >= 1 and d.subscribers_at_overload_risk > 0
    assert "overload" in d.recommendation
    assert {"CS-KKRI-04", "CS-KKRI-06"} == set(d.critical_sites_affected) and d.emergency_sites_affected == 0


def test_failure_validation(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.simulate_failure(conn, "nope")
    with pytest.raises(NotFoundError):
        tools.simulate_failure(conn, "ZZZZ-9999")


# ---------- stored simulations ----------


def test_runs_are_stored_and_retrievable(conn: sqlite3.Connection) -> None:
    first = tools.simulate_tilt(conn, _tilt(("KKRI-0143", 4.0))).data
    second = tools.simulate_failure(conn, "KKRI-0147").data
    assert int(second.sim_id.split("-")[1]) == int(first.sim_id.split("-")[1]) + 1
    record = tools.get_simulation(conn, first.sim_id).data
    assert record.kind == "tilt" and record.at.startswith("2026-11-14T07:00:00")
    assert record.params["changes"] == [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": 4.0}]
    assert record.result["recommended"] is False  # tilting one tower overloads the other neighbour
    assert any("KKRI-0144" in reason for reason in record.result["reasons"])
    with pytest.raises(NotFoundError):
        tools.get_simulation(conn, "SIM-9999")
    with pytest.raises(InvalidInputError):
        tools.get_simulation(conn, "1")


def test_twin_cannot_write_other_tables(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("DELETE FROM tower_kpi")
