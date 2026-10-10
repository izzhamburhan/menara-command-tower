from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from ontology_mcp import tools

EVIDENCE = [
    {"source": "tower-mcp", "tool": "tower_get_status", "call_id": "abc123", "ref": "KKRI-0142"},
    {"source": "grid-mcp", "tool": "grid_get_tower_power", "call_id": "def456"},
]


def _create(conn: sqlite3.Connection, **overrides: Any) -> Any:
    args: dict[str, Any] = {
        "enodeb_name": "KKRI-0142",
        "cause": "FLOOD",
        "cause_confidence": 0.93,
        "summary": "Tower down after feeder trip; river above danger level.",
        "ticket_ids": ["TK-88213"],
        "evidence": EVIDENCE,
        **overrides,
    }
    return tools.create_incident(conn, **args)


def test_create_returns_the_incident_with_its_provenance(conn: sqlite3.Connection) -> None:
    env = _create(conn)
    inc = env.data
    assert env.synthetic is True
    assert inc.incident_id.startswith("INC-") and inc.status == "OPEN"
    assert inc.cause == "FLOOD" and inc.cause_confidence == 0.93
    assert inc.ticket_ids == ["TK-88213"]
    assert [e.tool for e in inc.evidence] == ["tower_get_status", "grid_get_tower_power"]
    assert inc.created_at.startswith("2026-11-14T07:00:00")
    assert env.evidence[0].tool == "ontology_create_incident"


def test_get_and_list_round_trip(conn: sqlite3.Connection) -> None:
    created = _create(conn).data
    assert tools.get_incident(conn, created.incident_id).data == created
    listed = tools.list_incidents(conn).data
    assert [i.incident_id for i in listed.incidents] == [created.incident_id]
    assert tools.list_incidents(conn, status="RESOLVED").data.returned == 0
    assert tools.list_incidents(conn, enodeb_name="KKRI-0142").data.returned == 1


def test_one_open_incident_per_tower(conn: sqlite3.Connection) -> None:
    first = _create(conn).data
    with pytest.raises(InvalidInputError, match=first.incident_id):
        _create(conn)
    tools.update_incident(conn, first.incident_id, "RESOLVED")
    assert _create(conn).data.incident_id != first.incident_id


def test_duplicate_tickets_are_collapsed(conn: sqlite3.Connection) -> None:
    assert _create(conn, ticket_ids=["TK-88213", "TK-88213"]).data.ticket_ids == ["TK-88213"]


def test_a_future_ticket_cannot_be_linked_yet(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    with pytest.raises(NotFoundError, match="current scenario time"):
        _create(conn, ticket_ids=["TK-88249"])
    set_clock(12)
    assert _create(conn, ticket_ids=["TK-88213", "TK-88249"]).data.ticket_ids == ["TK-88213", "TK-88249"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"cause": "ALIENS"},
        {"cause_confidence": 1.2},
        {"cause_confidence": -0.1},
        {"summary": "no"},
        {"summary": "x" * 501},
        {"ticket_ids": ["88213"]},
        {"evidence": [{"source": "x"}]},
        {"evidence": [EVIDENCE[0]] * 31},
        {"enodeb_name": "kkri"},
    ],
)
def test_create_validation(conn: sqlite3.Connection, overrides: dict[str, Any]) -> None:
    with pytest.raises(InvalidInputError):
        _create(conn, **overrides)


def test_unknown_tower_and_incident(conn: sqlite3.Connection) -> None:
    with pytest.raises(NotFoundError):
        _create(conn, enodeb_name="ZZZZ-9999")
    with pytest.raises(NotFoundError):
        tools.get_incident(conn, "INC-9999")
    with pytest.raises(InvalidInputError):
        tools.get_incident(conn, "9999")


def test_status_moves_forward_only_and_collects_notes(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    inc = _create(conn).data
    mitigating = tools.update_incident(conn, inc.incident_id, "MITIGATING", note="Neighbours re-tilted").data
    assert mitigating.status == "MITIGATING" and [n.text for n in mitigating.notes] == ["Neighbours re-tilted"]
    with pytest.raises(InvalidInputError, match="Cannot move"):
        tools.update_incident(conn, inc.incident_id, "OPEN")
    set_clock(300)
    resolved = tools.update_incident(conn, inc.incident_id, "RESOLVED", note="Power restored, tilt rolled back").data
    assert resolved.status == "RESOLVED" and len(resolved.notes) == 2
    assert resolved.updated_at.startswith("2026-11-14T12:00:00")
    with pytest.raises(InvalidInputError, match="Cannot move"):
        tools.update_incident(conn, inc.incident_id, "MITIGATING")


def test_update_validation(conn: sqlite3.Connection) -> None:
    inc = _create(conn).data
    with pytest.raises(InvalidInputError):
        tools.update_incident(conn, inc.incident_id, "DONE")
    with pytest.raises(InvalidInputError):
        tools.update_incident(conn, inc.incident_id, "MITIGATING", note="  ")
    assert tools.get_incident(conn, inc.incident_id).data.status == "OPEN"


def test_list_validation(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.list_incidents(conn, status="LOST")
    with pytest.raises(InvalidInputError):
        tools.list_incidents(conn, limit=0)


def test_ontology_cannot_write_other_domains_tables(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("UPDATE ticket SET status = 'RESOLVED'")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        conn.execute("DELETE FROM tower_state")


def test_a_rejected_status_move_says_what_is_allowed(conn: sqlite3.Connection) -> None:
    inc = _create(conn).data
    with pytest.raises(InvalidInputError, match=r"allowed: MITIGATING, RESOLVED"):
        tools.update_incident(conn, inc.incident_id, "OPEN")
    tools.update_incident(conn, inc.incident_id, "RESOLVED")
    with pytest.raises(InvalidInputError, match=r"allowed: none \(already RESOLVED\)"):
        tools.update_incident(conn, inc.incident_id, "MITIGATING")
