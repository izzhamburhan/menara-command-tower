from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from usage_mcp.server import build_server


def test_server_registers_its_three_usage_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"usage_top_apps_in_area", "usage_get_tower_apps", "usage_app_trend"}


def test_a_tool_returns_an_envelope(db_file: Path) -> None:
    with sqlite3.connect(db_file) as raw:
        lat, lng = raw.execute("SELECT lat, lng FROM tower ORDER BY enodeb_name LIMIT 1").fetchone()
    result: Any = asyncio.run(build_server(db_file).call_tool("usage_top_apps_in_area", {"lat": lat, "lng": lng, "radius_km": 10, "hour": 21}))
    payload = json.loads(result[0][0].text) if isinstance(result, tuple) else result
    assert payload["synthetic"] is True and payload["evidence"] and payload["data"]["hour"] == 21
