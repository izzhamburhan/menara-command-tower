from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable

import pytest
from menara_core import kpi_overlay
from menara_core.errors import InvalidInputError, NotFoundError, TokenError
from ran_mcp import tools

NEIGHBOURS = ["KKRI-0143", "KKRI-0144"]
Token = Callable[..., str]


def _prb(conn: sqlite3.Connection, tower: str, t_min: int = 0) -> float:
    """PRB % of a tower at t_min after RAN changes, from the base KPI sample."""
    row = conn.execute(
        "SELECT * FROM tower_kpi WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (tower, t_min)
    ).fetchone()
    return kpi_overlay.adjust(conn, tower, t_min, row["prb_util"], row["drop_rate"], row["throughput_mbps"])[0]


def _tilt(conn: sqlite3.Connection, token: Token, delta: float = 4.0, towers: list[str] | None = None) -> str:
    names = towers or NEIGHBOURS
    env = tools.tilt_cells(
        conn,
        [{"enodeb_name": n, "tilt_delta_deg": delta} for n in names],
        token("ran_tilt_cells", names),
        reason="Relieve the overloaded neighbours",
    )
    return env.data.change_id


# ---------- tilt ----------


def test_a_working_tilt_takes_91_to_63_but_the_first_attempt_on_0143_barely_helps(
    conn: sqlite3.Connection, token: Token
) -> None:
    assert (_prb(conn, "KKRI-0143"), _prb(conn, "KKRI-0144")) == (91.0, 91.0)
    _tilt(conn, token)
    assert _prb(conn, "KKRI-0144") == 63.0  # efficacy 1.0
    assert _prb(conn, "KKRI-0143") == 88.2  # scripted failure: efficacy 0.1 on the first attempt


def test_the_second_attempt_on_0143_works_after_a_rollback(conn: sqlite3.Connection, token: Token) -> None:
    first = _tilt(conn, token, towers=["KKRI-0143"])
    assert _prb(conn, "KKRI-0143") == 88.2
    tools.revert_change(conn, first, token("ran_revert_tilt", ["KKRI-0143"]), reason="KPIs did not improve")
    assert _prb(conn, "KKRI-0143") == 91.0
    second = tools.tilt_cells(
        conn, [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": 4.0}], token("ran_tilt_cells", ["KKRI-0143"])
    ).data
    assert [i.attempt for i in second.items] == [2, 2, 2]
    assert _prb(conn, "KKRI-0143") == 63.0


def test_the_change_record_hides_the_efficacy_and_is_sandboxed(conn: sqlite3.Connection, token: Token) -> None:
    env = tools.tilt_cells(
        conn, [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": 4.0}], token("ran_tilt_cells", ["KKRI-0144"], "human:izzham")
    )
    change = env.data
    assert env.synthetic is True and env.warnings and change.sandboxed is True
    assert change.status == "ACTIVE" and change.approved_by == "human:izzham" and change.towers == ["KKRI-0144"]
    assert len(change.items) == 3  # a tower name tilts all its cells
    assert "efficacy" not in change.model_dump_json()
    assert env.evidence[0].tool == "ran_tilt_cells"


def test_a_single_cell_tilt_has_a_proportionally_smaller_effect(conn: sqlite3.Connection, token: Token) -> None:
    tools.tilt_cells(conn, [{"cell_id": "KKRI-0144-B1", "tilt_delta_deg": 6.0}], token("ran_tilt_cells", ["KKRI-0144"]))
    assert 63.0 < _prb(conn, "KKRI-0144") < 91.0  # 6 degrees on one of three cells is a 2 degree tower-wide change


def test_the_effect_starts_when_the_change_is_applied(
    conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    _tilt(conn, token, towers=["KKRI-0144"])
    assert _prb(conn, "KKRI-0144", t_min=12) == 63.0
    assert _prb(conn, "KKRI-0144", t_min=0) == 91.0


def test_config_shows_the_applied_tilt(conn: sqlite3.Connection, token: Token) -> None:
    before = tools.get_config(conn, "KKRI-0144").data
    change_id = _tilt(conn, token, towers=["KKRI-0144"])
    after = tools.get_config(conn, "KKRI-0144").data
    assert after.active_changes == [change_id] and before.active_changes == []
    for old, new in zip(before.cells, after.cells, strict=True):
        assert new.applied_delta_deg == 4.0 and new.tilt_deg == round(old.base_tilt_deg + 4.0, 2)


def test_tilt_limits(conn: sqlite3.Connection, token: Token) -> None:
    for bad in (
        [],
        [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": 9.0}],
        [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": "x"}],
        [{"tilt_delta_deg": 1.0}],
        [{"enodeb_name": "KKRI-0144", "cell_id": "KKRI-0144-B1", "tilt_delta_deg": 1.0}],
        [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": 1.0}, {"cell_id": "KKRI-0144-B1", "tilt_delta_deg": 1.0}],
    ):
        with pytest.raises(InvalidInputError):
            tools.tilt_cells(conn, bad, token("ran_tilt_cells", ["KKRI-0144"]))
    with pytest.raises(InvalidInputError, match="allowed range"):
        tools.tilt_cells(conn, [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": -8.0}], token("ran_tilt_cells", ["KKRI-0144"]))
    with pytest.raises(NotFoundError):
        tools.tilt_cells(conn, [{"enodeb_name": "ZZZZ-9999", "tilt_delta_deg": 1.0}], token("ran_tilt_cells", ["ZZZZ-9999"]))
    with pytest.raises(NotFoundError):
        tools.tilt_cells(conn, [{"cell_id": "KKRI-0144-B9", "tilt_delta_deg": 1.0}], token("ran_tilt_cells", ["KKRI-0144"]))
    assert tools.list_changes(conn).data.returned == 0


# ---------- tokens ----------


def test_a_forged_expired_or_misdirected_token_changes_nothing(conn: sqlite3.Connection, token: Token) -> None:
    change = [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": 4.0}]
    with pytest.raises(TokenError, match="signature"):
        tools.tilt_cells(conn, change, "forged.token")
    with pytest.raises(TokenError, match="Malformed"):
        tools.tilt_cells(conn, change, "nodot")
    with pytest.raises(TokenError, match="different"):
        tools.tilt_cells(conn, change, token("ran_reset_cell", ["KKRI-0144"]))  # wrong action
    with pytest.raises(TokenError, match="different"):
        tools.tilt_cells(conn, change, token("ran_tilt_cells", ["KKRI-0143"]))  # wrong target
    with pytest.raises(TokenError, match="expired"):
        tools.tilt_cells(conn, change, token("ran_tilt_cells", ["KKRI-0144"], ttl_s=-time.time_ns() // 10**9))
    assert tools.list_changes(conn).data.returned == 0 and _prb(conn, "KKRI-0144") == 91.0


def test_a_token_for_two_towers_does_not_cover_one_of_them(conn: sqlite3.Connection, token: Token) -> None:
    with pytest.raises(TokenError, match="different"):
        tools.tilt_cells(
            conn, [{"enodeb_name": "KKRI-0144", "tilt_delta_deg": 4.0}], token("ran_tilt_cells", NEIGHBOURS)
        )


# ---------- reset and revert ----------


def test_reset_cell_is_recorded_and_has_no_kpi_effect(conn: sqlite3.Connection, token: Token) -> None:
    change = tools.reset_cell(conn, "KKRI-0144-B1", token("ran_reset_cell", ["KKRI-0144"]), "Hung cell").data
    assert change.status == "COMPLETED" and change.action == "ran_reset_cell"
    assert [i.cell_id for i in change.items] == ["KKRI-0144-B1"]
    assert _prb(conn, "KKRI-0144") == 91.0
    with pytest.raises(InvalidInputError, match="nothing to revert"):
        tools.revert_change(conn, change.change_id, token("ran_revert_tilt", ["KKRI-0144"]))
    with pytest.raises(NotFoundError):
        tools.reset_cell(conn, "KKRI-0144-B9", token("ran_reset_cell", ["KKRI-0144"]))
    with pytest.raises(TokenError):
        tools.reset_cell(conn, "KKRI-0144-B1", token("ran_tilt_cells", ["KKRI-0144"]))


def test_revert_restores_the_kpis_and_cannot_be_repeated(conn: sqlite3.Connection, token: Token) -> None:
    change_id = _tilt(conn, token, towers=["KKRI-0144"])
    assert _prb(conn, "KKRI-0144") == 63.0
    reverted = tools.revert_change(conn, change_id, token("ran_revert_tilt", ["KKRI-0144"]), "KPIs fine, power is back").data
    assert reverted.status == "REVERTED" and reverted.reverted_at is not None
    assert "revert: KPIs fine" in reverted.reason
    assert _prb(conn, "KKRI-0144") == 91.0
    assert tools.get_config(conn, "KKRI-0144").data.active_changes == []
    with pytest.raises(InvalidInputError, match="nothing to revert"):
        tools.revert_change(conn, change_id, token("ran_revert_tilt", ["KKRI-0144"]))


def test_revert_needs_a_token_for_the_same_towers(conn: sqlite3.Connection, token: Token) -> None:
    change_id = _tilt(conn, token)
    with pytest.raises(TokenError, match="different"):
        tools.revert_change(conn, change_id, token("ran_revert_tilt", ["KKRI-0143"]))
    assert tools.get_change(conn, change_id).data.status == "ACTIVE"


def test_revert_keeps_the_history_so_earlier_samples_stay_changed(
    conn: sqlite3.Connection, token: Token, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    change_id = _tilt(conn, token, towers=["KKRI-0144"])
    set_clock(60)
    tools.revert_change(conn, change_id, token("ran_revert_tilt", ["KKRI-0144"]))
    assert _prb(conn, "KKRI-0144", t_min=30) == 63.0  # during the change
    assert _prb(conn, "KKRI-0144", t_min=60) == 91.0  # after the rollback


# ---------- reads and ownership ----------


def test_get_and_list_changes(conn: sqlite3.Connection, token: Token) -> None:
    first = _tilt(conn, token, towers=["KKRI-0144"])
    second = tools.reset_cell(conn, "KKRI-0145-B1", token("ran_reset_cell", ["KKRI-0145"])).data.change_id
    assert [c.change_id for c in tools.list_changes(conn).data.changes] == [second, first]
    assert [c.change_id for c in tools.list_changes(conn, enodeb_name="KKRI-0144").data.changes] == [first]
    assert [c.change_id for c in tools.list_changes(conn, status="COMPLETED").data.changes] == [second]
    assert tools.get_change(conn, first).data.towers == ["KKRI-0144"]
    for bad in ("MAYBE",):
        with pytest.raises(InvalidInputError):
            tools.list_changes(conn, status=bad)
    with pytest.raises(InvalidInputError):
        tools.list_changes(conn, limit=0)
    with pytest.raises(NotFoundError):
        tools.get_change(conn, "CHG-9999")
    with pytest.raises(InvalidInputError):
        tools.get_change(conn, "9999")


def test_ran_cannot_write_the_base_kpi_table(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("UPDATE tower_kpi SET prb_util = 0")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("UPDATE cell SET tilt_deg = 0")
