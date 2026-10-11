from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from care_mcp.server import build_server


def test_server_registers_its_four_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"care_get_impact", "care_draft_notice", "care_send_notice", "care_list_notices"}


def test_a_tool_returns_an_envelope(db_file: Path) -> None:
    result: Any = asyncio.run(build_server(db_file).call_tool("care_get_impact", {"enodeb_names": ["KKRI-0142"]}))
    payload = json.loads(result[0][0].text) if isinstance(result, tuple) else result
    assert payload["synthetic"] is True and payload["evidence"] and payload["data"]["affected_customers"] == 980
