from __future__ import annotations

import asyncio
from pathlib import Path

from sites_mcp.server import build_server


def test_server_registers_the_three_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"sites_get_site", "sites_list_in_bbox", "sites_for_tower"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("sites_for_tower", {"enodeb_name": "KKRI-0142"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["emergency_sites"] == 2
