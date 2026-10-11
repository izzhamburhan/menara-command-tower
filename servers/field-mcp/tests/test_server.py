from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from field_mcp.server import build_server


def test_server_registers_its_three_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"field_find_crew", "field_dispatch", "field_list_jobs"}


def test_a_tool_returns_an_envelope(db_file: Path) -> None:
    result: Any = asyncio.run(build_server(db_file).call_tool("field_find_crew", {"enodeb_name": "KKRI-0142", "skill": "POWER"}))
    payload = json.loads(result[0][0].text) if isinstance(result, tuple) else result
    assert payload["synthetic"] is True and payload["evidence"] and payload["data"]["access"] == "BOAT"
