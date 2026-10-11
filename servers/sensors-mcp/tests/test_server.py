from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from sensors_mcp.server import build_server


def test_server_registers_its_three_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"sensors_list_in_area", "sensors_get_readings", "sensors_get_alerts"}


def test_a_tool_returns_an_envelope(db_file: Path) -> None:
    result: Any = asyncio.run(build_server(db_file).call_tool("sensors_get_alerts", {"lat": 5.531, "lng": 102.197, "radius_km": 20}))
    payload = json.loads(result[0][0].text) if isinstance(result, tuple) else result
    assert payload["synthetic"] is True and payload["evidence"] and payload["data"]["returned"] >= 2
