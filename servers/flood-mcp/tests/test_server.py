from __future__ import annotations

import asyncio
from pathlib import Path

from flood_mcp.server import build_server


def test_server_registers_the_three_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"flood_get_gauge", "flood_list_gauges", "flood_check_point"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("flood_get_gauge", {"gauge_id": "GAUGE-KKRI-01"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["status"] == "DANGER"
