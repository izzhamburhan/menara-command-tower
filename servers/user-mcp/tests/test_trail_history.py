"""The trail can look back four weeks: a commuter's weekdays and weekend trips, oldest first."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError
from user_mcp import tools

FOUR_WEEKS = 40320


def _mall_goer(conn: sqlite3.Connection) -> str:
    return str(
        conn.execute(
            "SELECT v.msisdn_hash FROM subscriber_cell_visit v JOIN critical_site s ON s.serving_enodeb = v.enodeb_name "
            "AND s.kind = 'MALL' WHERE v.start_min < -1440 GROUP BY v.msisdn_hash ORDER BY COUNT(*) DESC, v.msisdn_hash LIMIT 1"
        ).fetchone()[0]
    )


def test_a_28_day_window_returns_the_whole_history_oldest_first_and_contiguous(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    data = tools.get_trail(conn, _mall_goer(conn), window_min=FOUR_WEEKS).data
    assert len(data.segments) > 40
    assert data.segments[0].arrived_at.startswith("2026-10-17T07:00")
    assert data.window_start.startswith("2026-10-17T07:12")
    for earlier, later in zip(data.segments, data.segments[1:], strict=False):
        assert earlier.left_at == later.arrived_at and earlier.current is False
    assert [s.current for s in data.segments].count(True) == 1 and data.segments[-1].current is True
    assert data.moves == len(data.segments) - 1


def test_the_default_window_is_still_one_day(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)
    digest = _mall_goer(conn)
    default = tools.get_trail(conn, digest).data
    assert default.window_min == 1440 and 1 <= len(default.segments) <= 8
    assert default.window_start.startswith("2026-11-13T07:12")


def test_a_window_over_four_weeks_is_rejected_with_the_range_in_the_message(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError, match="between 5 and 40320"):
        tools.get_trail(conn, _mall_goer(conn), window_min=FOUR_WEEKS + 1)


def test_serving_cell_and_area_lists_still_use_the_latest_started_visit(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    digest = _mall_goer(conn)
    latest = conn.execute(
        "SELECT enodeb_name FROM subscriber_cell_visit WHERE msisdn_hash = ? AND start_min <= 12 ORDER BY start_min DESC LIMIT 1",
        (digest,),
    ).fetchone()[0]
    assert tools.get_serving_cell(conn, digest).data.enodeb_name == latest
