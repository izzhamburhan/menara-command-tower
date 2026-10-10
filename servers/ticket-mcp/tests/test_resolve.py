from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from ticket_mcp import tools

STORM_END_MIN = 12


def test_resolving_a_ticket_closes_it_and_leaves_a_note(conn: sqlite3.Connection) -> None:
    env = tools.resolve(conn, ["TK-88213"], "Power restored, service back", resolved_by="menara-agent")
    assert env.synthetic is True and env.data.resolved == ["TK-88213"] and env.data.count == 1
    ticket = tools.get_ticket(conn, "TK-88213").data
    assert ticket.status == "RESOLVED" and ticket.resolved_at is not None
    assert ticket.resolved_at.startswith("2026-11-14T07:00:00")
    assert [n.text for n in ticket.notes] == ["Resolved: Power restored, service back"]
    assert env.evidence[0].tool == "ticket_resolve" and env.evidence[0].ref == "TK-88213"


def test_the_whole_cluster_can_be_closed_at_once(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(STORM_END_MIN)
    cluster = tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=30).data
    ids = [t.ticket_id for t in cluster.tickets]
    result = tools.resolve(conn, ids, "Service restored").data
    assert result.count == 37 and result.already_resolved == []
    after = tools.cluster_by_location(conn, "TK-88213", radius_km=15, window_min=30).data
    assert after.count == 37 and {t.status for t in after.tickets} == {"RESOLVED"}


def test_resolving_twice_skips_what_is_already_closed(conn: sqlite3.Connection) -> None:
    tools.resolve(conn, ["TK-88213"], "Done")
    again = tools.resolve(conn, ["TK-88213", "TK-88213"], "Done again").data
    assert again.resolved == [] and again.already_resolved == ["TK-88213"]
    assert len(tools.get_ticket(conn, "TK-88213").data.notes) == 1


def test_a_resolution_is_not_visible_before_it_happens(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(60)
    tools.resolve(conn, ["TK-88213"], "Back")
    set_clock(0)
    assert tools.get_ticket(conn, "TK-88213").data.status == "OPEN"
    set_clock(60)
    assert tools.get_ticket(conn, "TK-88213").data.status == "RESOLVED"


def test_validation(conn: sqlite3.Connection) -> None:
    for kwargs in (
        {"ticket_ids": [], "note": "x"},
        {"ticket_ids": ["TK-88213"], "note": "  "},
        {"ticket_ids": ["TK-88213"], "note": "x" * 1001},
        {"ticket_ids": ["TK-88213"], "note": "ok", "resolved_by": ""},
        {"ticket_ids": ["88213"], "note": "ok"},
        {"ticket_ids": [f"TK-{80000 + i}" for i in range(201)], "note": "ok"},
    ):
        with pytest.raises(InvalidInputError):
            tools.resolve(conn, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(NotFoundError, match="current scenario time"):
        tools.resolve(conn, ["TK-88249"], "ok")  # not raised yet at T0
    assert tools.get_ticket(conn, "TK-88213").data.status == "OPEN"