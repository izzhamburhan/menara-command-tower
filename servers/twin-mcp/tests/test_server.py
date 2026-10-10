from __future__ import annotations

import asyncio
from pathlib import Path

from twin_mcp.server import build_server


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"twin_simulate_failure", "twin_simulate_tilt", "twin_get_simulation"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    changes = [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": 4.0}]
    result = asyncio.run(build_server(db_file).call_tool("twin_simulate_tilt", {"changes": changes}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["tilted"][0]["predicted_prb"] == 63.0
