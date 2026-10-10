from __future__ import annotations

import asyncio
from pathlib import Path

from ticket_mcp.server import build_server


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"ticket_get_ticket", "ticket_cluster_by_location", "ticket_add_note", "ticket_resolve"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("ticket_get_ticket", {"ticket_id": "TK-88213"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["ticket_id"] == "TK-88213"
