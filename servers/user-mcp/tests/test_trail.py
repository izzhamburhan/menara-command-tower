"""A subscriber's trail: which cells they were on, when they arrived and left."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from user_mcp import tools


def _mover(conn: sqlite3.Connection) -> str:
    return str(
        conn.execute(
            "SELECT msisdn_hash FROM subscriber_cell_visit GROUP BY msisdn_hash "
            "HAVING COUNT(DISTINCT enodeb_name) > 1 ORDER BY msisdn_hash LIMIT 1"
        ).fetchone()[0]
    )


def _stayer(conn: sqlite3.Connection) -> str:
    return str(conn.execute("SELECT msisdn_hash FROM subscriber WHERE enodeb_name = 'KKRI-0142' LIMIT 1").fetchone()[0])


def _visits(conn: sqlite3.Connection, digest: str) -> list[tuple[int, str]]:
    return [
        (r["start_min"], r["enodeb_name"])
        for r in conn.execute("SELECT start_min, enodeb_name FROM subscriber_cell_visit WHERE msisdn_hash = ? ORDER BY start_min", (digest,))
    ]


def test_a_stationary_subscriber_has_one_current_segment(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    env = tools.get_trail(conn, _stayer(conn))
    data = env.data
    assert len(data.segments) == 1 and data.moves == 0 and data.distinct_towers == 1
    seg = data.segments[0]
    assert seg.enodeb_name == "KKRI-0142" and seg.current is True and seg.left_at is None
    assert seg.arrived_at.startswith("2026-11-13T07:00") and seg.duration_min == 1440  # minutes inside the window
    assert data.location_precision == "cell" and env.evidence[0].tool == "user_get_trail"


def test_a_commuter_has_home_transit_and_work_segments_with_times(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    digest = _mover(conn)
    visits = _visits(conn, digest)
    set_clock(480)
    data = tools.get_trail(conn, digest, window_min=2880).data
    assert [s.enodeb_name for s in data.segments] == [t for _, t in visits]
    assert data.segments[-1].current is True and data.segments[-1].left_at is None
    for earlier, later in zip(data.segments, data.segments[1:], strict=False):
        assert earlier.left_at == later.arrived_at and earlier.current is False
    assert data.moves == len(visits) - 1 and data.distinct_towers == len({t for _, t in visits})


def test_the_trail_never_extends_past_the_clock(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    digest = _mover(conn)
    visits = _visits(conn, digest)
    first_move_today = next(start for start, _ in visits if start >= 0)
    set_clock(first_move_today - 1)
    data = tools.get_trail(conn, digest, window_min=2880).data
    assert data.segments[-1].current is True and data.segments[-1].enodeb_name != visits[-1][1]
    assert all(s.arrived_at <= data.segments[-1].arrived_at for s in data.segments)


def test_window_selects_overlapping_segments_and_clips_durations(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    digest = _mover(conn)
    set_clock(480)
    short = tools.get_trail(conn, digest, window_min=60).data
    full = tools.get_trail(conn, digest, window_min=2880).data
    assert 1 <= len(short.segments) < len(full.segments)
    assert short.segments[-1].enodeb_name == full.segments[-1].enodeb_name
    assert sum(s.duration_min for s in short.segments) <= 60


def test_serving_cell_follows_the_trail_and_matches_the_table_at_minute_0(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    digest = _mover(conn)
    row = conn.execute("SELECT serving_cell, enodeb_name FROM subscriber WHERE msisdn_hash = ?", (digest,)).fetchone()
    set_clock(0)
    now = tools.get_serving_cell(conn, digest).data
    assert (now.serving_cell, now.enodeb_name) == (row["serving_cell"], row["enodeb_name"])
    set_clock(480)
    later = tools.get_serving_cell(conn, digest).data
    last = conn.execute(
        "SELECT serving_cell, enodeb_name FROM subscriber_cell_visit WHERE msisdn_hash = ? ORDER BY start_min DESC LIMIT 1", (digest,)
    ).fetchone()
    assert (later.serving_cell, later.enodeb_name) == (last["serving_cell"], last["enodeb_name"])
    assert later.enodeb_name != now.enodeb_name


def test_trail_validation_and_unknown_subscriber(conn: sqlite3.Connection) -> None:
    for bad in (4, 2881):
        with pytest.raises(InvalidInputError):
            tools.get_trail(conn, _stayer(conn), window_min=bad)
    with pytest.raises(InvalidInputError):
        tools.get_trail(conn, "not-a-hash")
    with pytest.raises(NotFoundError):
        tools.get_trail(conn, "0" * 16)