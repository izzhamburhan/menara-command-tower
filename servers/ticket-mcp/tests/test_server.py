from __future__ import annotations

import asyncio
from pathlib import Path

from ticket_mcp.server import build_server


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {
        "ticket_get_ticket",
        "ticket_cluster_by_location",
        "ticket_add_note",
        "ticket_resolve",
        "ticket_create_ntt",
        "ticket_get_ntt",
        "ticket_list_ntts",
        "ticket_link_ctts",
        "ticket_unlink_ctt",
        "ticket_resolve_ntt",
        "ticket_check_mcmc",
    }


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("ticket_get_ticket", {"ticket_id": "TK-88213"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["ticket_id"] == "TK-88213"


def test_tool_call_create_ntt(db_file: Path) -> None:
    result = asyncio.run(
        build_server(db_file).call_tool(
            "ticket_create_ntt",
            {
                "network_element_id": "KKRI-0142",
                "fault_type": "POWER",
                "severity": "CRITICAL",
                "summary": "Mains failure on feeder",
            },
        )
    )
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["network_element_id"] == "KKRI-0142"
    assert payload["data"]["status"] == "IN_PROGRESS"
