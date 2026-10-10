from __future__ import annotations

import asyncio
from pathlib import Path

from ontology_mcp.server import build_server

EXPECTED = {
    "ontology_blast_radius",
    "ontology_neighbours",
    "ontology_upstream_of",
    "ontology_create_incident",
    "ontology_get_incident",
    "ontology_list_incidents",
    "ontology_update_incident",
}


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == EXPECTED


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("ontology_blast_radius", {"site": "KKRI-0142"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["towers_at_risk"] == 11
