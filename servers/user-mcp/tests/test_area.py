"""Subscribers on a tower or inside a circle (synthetic sample), and who is where as the clock moves."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from user_mcp import tools

KK_CENTRE = (5.531, 102.197)  # KKRI-0142


def _mover(conn: sqlite3.Connection) -> tuple[str, str, str]:
    """(hash, home tower, work tower) of the first subscriber who commutes."""
    row = conn.execute(
        "SELECT msisdn_hash FROM subscriber_cell_visit GROUP BY msisdn_hash "
        "HAVING COUNT(DISTINCT enodeb_name) > 1 ORDER BY msisdn_hash LIMIT 1"
    ).fetchone()
    digest = row["msisdn_hash"]
    home = conn.execute("SELECT enodeb_name FROM subscriber WHERE msisdn_hash = ?", (digest,)).fetchone()[0]
    work = conn.execute(
        "SELECT enodeb_name FROM subscriber_cell_visit WHERE msisdn_hash = ? ORDER BY start_min DESC LIMIT 1", (digest,)
    ).fetchone()[0]
    return digest, home, work


def test_list_on_tower_returns_sampled_and_estimated_counts(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    env = tools.list_on_tower(conn, "KKRI-0142")
    data = env.data
    assert data.withheld is False and data.subscribers_total == 40 and data.returned == 40 and data.truncated is False
    assert len(data.towers) == 1
    tower = data.towers[0]
    assert (tower.enodeb_name, tower.subscribers_sampled, tower.subscribers_est) == ("KKRI-0142", 40, 980)
    assert (tower.cell_lat, tower.cell_lng) == (5.531, 102.197)
    assert all(s.enodeb_name == "KKRI-0142" for s in data.subscribers)
    assert env.synthetic is True and env.evidence[0].tool == "user_list_on_tower" and env.evidence[0].ref == "KKRI-0142"


def test_flooded_tower_subscribers_are_detached_and_no_service(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    flooded = tools.list_on_tower(conn, "KKRI-0142").data.subscribers
    assert flooded and all(not s.attached and s.latest_label == "NO_SERVICE" for s in flooded)


def test_overloaded_neighbour_subscribers_are_degraded_not_silent(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    neighbour = tools.list_on_tower(conn, "KKRI-0143").data.subscribers
    assert all(s.attached for s in neighbour)
    labels = {s.latest_label for s in neighbour}
    assert "NO_SERVICE" not in labels and labels & {"POOR", "FAIR"}


def test_area_around_a_town_lists_its_towers_and_subscribers(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    env = tools.list_in_area(conn, *KK_CENTRE, radius_km=5)
    data = env.data
    names = {t.enodeb_name for t in data.towers}
    assert {"KKRI-0142", "KKRI-0143"} <= names
    assert data.subscribers_total == sum(t.subscribers_sampled for t in data.towers) == data.returned
    assert {s.enodeb_name for s in data.subscribers} == names
    assert (data.center.lat, data.center.lng, data.radius_km) == (*KK_CENTRE, 5)
    assert env.evidence[0].tool == "user_list_in_area"


def test_an_empty_area_is_empty_not_withheld(conn: sqlite3.Connection) -> None:
    data = tools.list_in_area(conn, 0.0, 0.0, radius_km=1).data
    assert data.subscribers == [] and data.towers == [] and data.subscribers_total == 0 and data.withheld is False


def test_a_small_group_is_withheld(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools, "MIN_AGGREGATE_COUNT", 1000)  # pretend 40 is a small group
    env = tools.list_on_tower(conn, "KKRI-0142")
    assert env.data.withheld is True and env.data.subscribers == [] and env.data.towers == []
    assert env.data.subscribers_total is None and env.warnings


def test_limit_truncates_but_the_total_is_kept(conn: sqlite3.Connection) -> None:
    data = tools.list_on_tower(conn, "KKRI-0142", limit=10).data
    assert data.returned == 10 and data.subscribers_total == 40 and data.truncated is True
    assert data.towers[0].subscribers_sampled == 40


def test_a_mover_appears_on_the_new_tower_after_they_move(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    digest, home, work = _mover(conn)
    set_clock(0)
    assert digest in {s.msisdn_hash for s in tools.list_on_tower(conn, home, limit=500).data.subscribers}
    assert digest not in {s.msisdn_hash for s in tools.list_on_tower(conn, work, limit=500).data.subscribers}
    set_clock(200)
    assert digest not in {s.msisdn_hash for s in tools.list_on_tower(conn, home, limit=500).data.subscribers}
    assert digest in {s.msisdn_hash for s in tools.list_on_tower(conn, work, limit=500).data.subscribers}


def test_cells_are_cell_level_and_hashes_are_masked(conn: sqlite3.Connection) -> None:
    data = tools.list_on_tower(conn, "KKRI-0143").data
    assert data.location_precision == "cell"
    assert all(len(s.msisdn_hash) == 16 and s.serving_cell.startswith("KKRI-0143-") for s in data.subscribers)


@pytest.mark.parametrize(
    "args",
    [
        {"lat": 91.0, "lng": 102.0, "radius_km": 5},
        {"lat": 5.0, "lng": 181.0, "radius_km": 5},
        {"lat": 5.0, "lng": 102.0, "radius_km": 0.05},
        {"lat": 5.0, "lng": 102.0, "radius_km": 101},
        {"lat": 5.0, "lng": 102.0, "radius_km": 5, "limit": 0},
        {"lat": 5.0, "lng": 102.0, "radius_km": 5, "limit": 501},
    ],
)
def test_area_validation(conn: sqlite3.Connection, args: dict[str, float | int]) -> None:
    with pytest.raises(InvalidInputError):
        tools.list_in_area(conn, **args)  # type: ignore[arg-type]


def test_tower_validation_and_unknown_tower(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.list_on_tower(conn, "kkri")
    with pytest.raises(InvalidInputError):
        tools.list_on_tower(conn, "KKRI-0142", limit=0)
    with pytest.raises(NotFoundError):
        tools.list_on_tower(conn, "ZZZZ-9999")

# ---------- follow-ups from the live runs ----------


def test_the_estimate_total_is_the_sum_over_the_towers(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    data = tools.list_in_area(conn, *KK_CENTRE, radius_km=5).data
    assert data.subscribers_est_total == sum(t.subscribers_est or 0 for t in data.towers) > 980
    assert tools.list_on_tower(conn, "KKRI-0142").data.subscribers_est_total == 980


def test_the_estimate_total_is_null_when_withheld_and_zero_when_empty(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert tools.list_in_area(conn, 0.0, 0.0, radius_km=1).data.subscribers_est_total == 0
    monkeypatch.setattr(tools, "MIN_AGGREGATE_COUNT", 1000)
    assert tools.list_on_tower(conn, "KKRI-0142").data.subscribers_est_total is None


def _expected_changes(conn: sqlite3.Connection, digest: str, now: int) -> int:
    return int(
        conn.execute(
            "SELECT COUNT(*) FROM subscriber_cell_visit WHERE msisdn_hash = ? AND start_min <= ? AND start_min > ? "
            "AND start_min > (SELECT MIN(start_min) FROM subscriber_cell_visit WHERE msisdn_hash = ?)",
            (digest, now, now - 1440, digest),
        ).fetchone()[0]
    )


def test_cell_changes_in_24h_is_zero_for_stayers_and_follows_the_clock_for_commuters(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    digest, home, _ = _mover(conn)
    for minute in (0, 200, 480):
        set_clock(minute)
        rows = {s.msisdn_hash: s for s in tools.list_on_tower(conn, home, limit=500).data.subscribers}
        if digest in rows:
            assert rows[digest].cell_changes_24h == _expected_changes(conn, digest, minute)
    set_clock(200)
    flooded = tools.list_on_tower(conn, "KKRI-0142").data.subscribers
    assert flooded and all(s.cell_changes_24h == 0 for s in flooded)
    work = _mover(conn)[2]
    on_work = {s.msisdn_hash: s for s in tools.list_on_tower(conn, work, limit=500).data.subscribers}
    assert on_work[digest].cell_changes_24h == _expected_changes(conn, digest, 200) > 0
