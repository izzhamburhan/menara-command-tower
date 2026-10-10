from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from ticket_mcp import tools

STORM_END_MIN = 12


def test_first_ticket_lands_at_t0(conn: sqlite3.Connection) -> None:
    env = tools.get_ticket(conn, "TK-88213")
    assert env.synthetic is True
    assert env.data.summary == "No data since 7am, banjir kat Kuala Krai"
    assert env.data.service == "UniFi Mobile"
    assert env.data.created_at.startswith("2026-11-14T07:00:00")
    assert len(env.data.customer_ref) == 16
    assert env.evidence[0].tool == "ticket_get_ticket"


def test_ticket_storm_is_hidden_until_the_clock_reaches_it(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(0)
    visible = tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=60).data
    assert visible.count == 1
    set_clock(STORM_END_MIN)
    assert tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=60).data.count == 37


def test_future_ticket_does_not_exist_yet(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError, match="current scenario time"):
        tools.get_ticket(conn, "TK-88249")


def test_cluster_reports_the_flood_pattern(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(STORM_END_MIN)
    cluster = tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=30).data
    assert cluster.count == 37 and cluster.returned == 37 and not cluster.truncated
    assert 1 <= cluster.span_min <= STORM_END_MIN
    assert cluster.centroid is not None and 5.4 < cluster.centroid.lat < 5.7
    assert cluster.top_locations[0].count >= 1
    assert {t.category for t in cluster.tickets} == {"No data"}
    assert max(t.distance_km for t in cluster.tickets) <= 15


def test_cluster_radius_and_window_narrow_the_result(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(STORM_END_MIN)
    wide = tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=60).data.count
    tight = tools.cluster_by_location(conn, "TK-88213", radius_km=3, window_min=60).data.count
    brief = tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=3).data.count
    assert tight < wide and brief < wide


def test_old_resolved_tickets_do_not_join_the_cluster(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(STORM_END_MIN)
    ids = {t.ticket_id for t in tools.cluster_by_location(conn, "TK-88213", window_min=60).data.tickets}
    assert all(88213 <= int(i.split("-")[1]) <= 88249 for i in ids)


def test_cluster_limit_truncates_but_keeps_full_count(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(STORM_END_MIN)
    env = tools.cluster_by_location(conn, "TK-88213", limit=5)
    assert env.data.count == 37 and env.data.returned == 5 and env.data.truncated
    assert env.warnings


@pytest.mark.parametrize(
    ("kwargs"),
    [{"radius_km": 0.0}, {"radius_km": 101.0}, {"window_min": 0}, {"window_min": 1441}, {"limit": 0}],
)
def test_cluster_rejects_bad_arguments(conn: sqlite3.Connection, kwargs: dict[str, float]) -> None:
    with pytest.raises(InvalidInputError):
        tools.cluster_by_location(conn, "TK-88213", **kwargs)  # type: ignore[arg-type]


def test_ids_are_validated(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_ticket(conn, "88213")
    with pytest.raises(NotFoundError):
        tools.get_ticket(conn, "TK-99999999")


def test_add_note_persists_and_shows_on_the_ticket(conn: sqlite3.Connection) -> None:
    added = tools.add_note(conn, "TK-88213", "  Tower KKRI-0142 is DOWN (mains fail).  ", author="menara-agent")
    assert added.data.note.text == "Tower KKRI-0142 is DOWN (mains fail)."
    assert added.data.note.at.startswith("2026-11-14T07:00:00")
    notes = tools.get_ticket(conn, "TK-88213").data.notes
    assert [n.author for n in notes] == ["menara-agent"]


@pytest.mark.parametrize(("text", "author"), [("", "agent"), ("   ", "agent"), ("x" * 1001, "agent"), ("ok", "")])
def test_add_note_rejects_bad_input(conn: sqlite3.Connection, text: str, author: str) -> None:
    with pytest.raises(InvalidInputError):
        tools.add_note(conn, "TK-88213", text, author)


def test_add_note_cannot_touch_other_tables(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("UPDATE ticket SET status = 'RESOLVED'")
