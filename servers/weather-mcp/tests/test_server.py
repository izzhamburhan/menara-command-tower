from __future__ import annotations

import asyncio
from pathlib import Path

from weather_mcp.server import build_server


def test_server_registers_the_two_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"weather_get_rainfall", "weather_get_lightning"}


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("weather_get_rainfall", {"lat": 5.531, "lng": 102.197}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["intensity"] == "VERY_HEAVY"
