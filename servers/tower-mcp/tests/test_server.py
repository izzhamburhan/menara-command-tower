from __future__ import annotations

import asyncio
from pathlib import Path

from tower_mcp.server import build_server
from tower_mcp.source_sqlite import SqliteSourceFactory

EXPECTED_TOOLS = {"tower_get_status", "tower_list_in_bbox", "tower_get_kpi", "tower_get_alarms"}


def test_server_registers_the_four_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(SqliteSourceFactory(db_file)).list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(SqliteSourceFactory(db_file)).call_tool("tower_get_status", {"enodeb_name": "KKRI-0142"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["status"] == "DOWN"
    assert payload["evidence"][0]["tool"] == "tower_get_status"