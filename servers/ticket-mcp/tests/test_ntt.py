"""Tests for NTT (Network Trouble Ticket) tools in ticket-mcp."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from ticket_mcp.models import NttDetail
from ticket_mcp.tools import (
    create_ntt,
    get_ntt,
    get_ticket,
    link_ctts,
    list_ntts,
    resolve_ntt,
    unlink_ctt,
)


def test_ntt_models_importable() -> None:
    detail = NttDetail(
        ntt_id="NTT-0001",
        created_at="2026-11-14T07:12:00+08:00",
        network_element_id="KKRI-0142",
        fault_type="POWER",
        severity="CRITICAL",
        status="IN_PROGRESS",
        summary="Mains failure",
        ctt_count=1,
        linked_ctt_ids=["TK-88213"],
        notes=[],
        resolved_at=None,
        resolved_by=None,
        resolution_note=None,
        mcmc_closure_sent=False,
        mcmc_comprehensive_required=False,
    )
    assert detail.ntt_id == "NTT-0001"
    assert detail.ctt_count == 1
    assert detail.mcmc_closure_sent is False


def test_create_ntt_and_deduplicate_active_ne(conn: sqlite3.Connection) -> None:
    # 1. Create fresh NTT
    res = create_ntt(
        conn,
        network_element_id="KKRI-0142",
        fault_type="POWER",
        severity="CRITICAL",
        summary="Mains failure at tower KKRI-0142",
        ctt_ticket_ids=["TK-88213"],
    )
    assert res.data.ntt_id == "NTT-0001"
    assert res.data.network_element_id == "KKRI-0142"
    assert res.data.status == "IN_PROGRESS"
    assert res.data.ctt_count == 1
    assert res.data.linked_ctt_ids == ["TK-88213"]
    assert res.warnings == []

    # 2. Duplicate active NE check: Reuses existing active NTT and links new CTT
    dup = create_ntt(
        conn,
        network_element_id="KKRI-0142",
        fault_type="FLOOD",
        severity="MAJOR",
        summary="Another complaint for same tower",
    )
    assert dup.data.ntt_id == "NTT-0001"
    assert len(dup.warnings) == 1
    assert "reused" in dup.warnings[0]


def test_get_ntt_and_list_ntts(conn: sqlite3.Connection) -> None:
    res1 = create_ntt(
        conn,
        network_element_id="KKRI-0142",
        fault_type="POWER",
        severity="CRITICAL",
        summary="Tower outage",
    )
    create_ntt(
        conn,
        network_element_id="KKRI-0143",
        fault_type="RAN",
        severity="MAJOR",
        summary="High PRB load",
    )

    # Get single NTT
    ntt = get_ntt(conn, res1.data.ntt_id)
    assert ntt.data.network_element_id == "KKRI-0142"

    # List all
    all_ntts = list_ntts(conn)
    assert all_ntts.data.total == 2
    assert len(all_ntts.data.ntts) == 2

    # Filter by NE
    filtered = list_ntts(conn, network_element_id="KKRI-0143")
    assert filtered.data.total == 1
    assert filtered.data.ntts[0].network_element_id == "KKRI-0143"


def test_link_and_unlink_ctts(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(12)  # Minute 12: tickets exist
    ntt_env = create_ntt(
        conn,
        network_element_id="KKRI-0142",
        fault_type="POWER",
        severity="CRITICAL",
        summary="Mains failure",
    )
    ntt_id = ntt_env.data.ntt_id

    # Link CTT
    link_res = link_ctts(conn, ntt_id=ntt_id, ctt_ticket_ids=["TK-88213"])
    assert link_res.data.linked == ["TK-88213"]
    assert link_res.data.ctt_count == 1

    # Link again -> already linked
    link_res2 = link_ctts(conn, ntt_id=ntt_id, ctt_ticket_ids=["TK-88213"])
    assert link_res2.data.already_linked == ["TK-88213"]
    assert link_res2.data.linked == []

    # Unlink
    unlink_res = unlink_ctt(conn, ntt_id=ntt_id, ctt_ticket_id="TK-88213")
    assert unlink_res.data.unlinked_ticket_id == "TK-88213"
    assert unlink_res.data.ctt_count == 0


def test_resolve_ntt_cascades_to_linked_ctts(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    set_clock(12)
    ntt_env = create_ntt(
        conn,
        network_element_id="KKRI-0142",
        fault_type="POWER",
        severity="CRITICAL",
        summary="Mains failure",
        ctt_ticket_ids=["TK-88213"],
    )
    ntt_id = ntt_env.data.ntt_id

    # Resolve NTT
    res = resolve_ntt(conn, ntt_id=ntt_id, resolution_note="Genset deployed, tower back up")
    assert res.data.status == "RESOLVED"
    assert res.data.resolved_ctts == ["TK-88213"]

    # Verify linked CTT is now RESOLVED
    ctt = get_ticket(conn, "TK-88213")
    assert ctt.data.status == "RESOLVED"
    assert any(f"Resolved via NTT {ntt_id}" in n.text for n in ctt.data.notes)


def test_ntt_invalid_inputs_and_not_found(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        create_ntt(conn, network_element_id="", fault_type="POWER", severity="CRITICAL", summary="Too short")

    with pytest.raises(InvalidInputError):
        create_ntt(conn, network_element_id="KKRI-0142", fault_type="INVALID", severity="CRITICAL", summary="Bad fault")

    with pytest.raises(NotFoundError):
        get_ntt(conn, "NTT-9999")

    # Double resolve raises InvalidInputError
    ntt = create_ntt(conn, network_element_id="KKRI-0142", fault_type="POWER", severity="CRITICAL", summary="Power down")
    resolve_ntt(conn, ntt_id=ntt.data.ntt_id, resolution_note="Fixed")
    with pytest.raises(InvalidInputError):
        resolve_ntt(conn, ntt_id=ntt.data.ntt_id, resolution_note="Already fixed")


def test_mcmc_eligibility_and_auto_send_on_resolve(
    conn: sqlite3.Connection, set_clock: Callable[[int], None]
) -> None:
    from ticket_mcp.tools import check_mcmc

    set_clock(0)
    ntt_env = create_ntt(
        conn,
        network_element_id="KKRI-0142",
        fault_type="POWER",
        severity="CRITICAL",
        summary="Mains failure at tower KKRI-0142",
    )
    ntt_id = ntt_env.data.ntt_id

    # 1. At T=0 (outage duration < 120 min), MCMC cannot send yet
    check1 = check_mcmc(conn, ntt_id)
    assert check1.data.can_send is False
    assert any("duration" in r.lower() for r in check1.data.reasons)

    # 2. Advance clock to minute 150 (outage duration 150 >= 120 mins)
    set_clock(150)
    check2 = check_mcmc(conn, ntt_id)
    assert check2.data.can_send is True
    assert check2.data.can_send_display_message == "EMAILED TO MCMC"

    # 3. Resolve NTT -> Auto-dispatches MCMC closure notice and flags comprehensive report due in 3 days
    res = resolve_ntt(conn, ntt_id=ntt_id, resolution_note="Power restored to tower")
    assert res.data.mcmc.can_send is True
    assert res.data.mcmc.is_mcmc_closure_sent is True
    assert res.data.mcmc.is_mcmc_comprehensive_required is True
    assert res.data.mcmc.comprehensive_report_aging_days == 3

    # 4. Check NTT detail reflects MCMC status and auto-logged note
    detail = get_ntt(conn, ntt_id)
    assert detail.data.mcmc_closure_sent is True
    assert detail.data.mcmc_comprehensive_required is True
    assert any("MCMC Closure" in n.text for n in detail.data.notes)

