from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from events_mcp.server import build_server


def test_server_registers_its_three_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"events_list_upcoming", "events_forecast_load", "events_capacity_plan"}


def test_a_tool_returns_an_envelope(db_file: Path) -> None:
    result: Any = asyncio.run(build_server(db_file).call_tool("events_forecast_load", {"event_id": "EVT-001"}))
    payload = json.loads(result[0][0].text) if isinstance(result, tuple) else result
    assert payload["synthetic"] is True and payload["evidence"] and len(payload["data"]["towers"]) == 5
