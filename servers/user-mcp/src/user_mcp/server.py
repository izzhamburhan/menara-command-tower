"""user-mcp server. Run: `uv run --package user-mcp python -m user_mcp [--transport streamable-http --port 8103]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from user_mcp import tools

NAME = "user"
DEFAULT_PORT = 8103
INSTRUCTIONS = (
    "Subscriber serving cell and experience for UniFi Mobile. ALL DATA IS SYNTHETIC. "
    "PII is masked: subscribers are identified only by msisdn_hash (get it from a ticket's customer_ref) "
    "and location is cell-level, never individual. Read-only."
)


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Serving cell, tower, attach state and cell-level location of one subscriber (by msisdn_hash). "
        "If not attached, serving_cell is the last known cell."
    )
    def user_get_serving_cell(msisdn_hash: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_serving_cell(conn, msisdn_hash))

    @mcp.tool(
        description="Experience score (0-100), label, throughput, drop events and RSRP for one subscriber "
        "over the last window_min minutes, plus the latest sample."
    )
    def user_get_experience(msisdn_hash: str, window_min: int = 120) -> dict[str, Any]:
        return run(lambda conn: tools.get_experience(conn, msisdn_hash, window_min))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="user-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
