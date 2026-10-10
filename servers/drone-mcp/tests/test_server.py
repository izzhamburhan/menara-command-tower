from __future__ import annotations

import asyncio
from pathlib import Path

from drone_mcp.server import build_server


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"drone_list_drones", "drone_dispatch", "drone_get_mission", "drone_list_missions"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("drone_list_drones", {}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["returned"] == 12
