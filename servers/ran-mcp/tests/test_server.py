from __future__ import annotations

import asyncio
from pathlib import Path

from ran_mcp.server import build_server

EXPECTED = {
    "ran_get_config",
    "ran_tilt_cells",
    "ran_reset_cell",
    "ran_revert_change",
    "ran_get_change",
    "ran_list_changes",
}


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == EXPECTED


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("ran_get_config", {"enodeb_name": "KKRI-0143"}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert len(payload["data"]["cells"]) == 3
