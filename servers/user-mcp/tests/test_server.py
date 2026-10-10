from __future__ import annotations

import asyncio
from pathlib import Path

from user_mcp.server import build_server


def test_server_registers_the_two_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == {"user_get_serving_cell", "user_get_experience"}
