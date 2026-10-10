from __future__ import annotations

import asyncio
from pathlib import Path

from grid_mcp.server import build_server


def test_server_registers_the_three_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"grid_get_tower_power", "grid_get_feeder_status", "grid_list_outages"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("grid_get_tower_power", {"enodeb_name": "KKRI-0142"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["feeder"]["status"] == "TRIPPED"
