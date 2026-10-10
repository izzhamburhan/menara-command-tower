"""flood-mcp server. Run: `uv run --package flood-mcp python -m flood_mcp [--transport streamable-http --port 8107]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from flood_mcp import tools

NAME = "flood"
DEFAULT_PORT = 8107
INSTRUCTIONS = (
    "River gauges and flood extent. ALL DATA IS SYNTHETIC; gauge thresholds are invented for the demo. "
    "Read-only. Every response has evidence[] naming the call that produced it."
)


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="One river gauge: level, warning and danger levels, status (NORMAL, WARNING, DANGER), "
        "trend over the last 3 hours (RISING, FALLING, STEADY) and metres above danger."
    )
    def flood_get_gauge(gauge_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_gauge(conn, gauge_id))

    @mcp.tool(
        description="River gauges inside a lat/lng bounding box with their current level and status. "
        "status filter: NORMAL, WARNING or DANGER."
    )
    def flood_list_gauges(
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return run(lambda conn: tools.list_gauges(conn, min_lat, min_lng, max_lat, max_lng, status, limit))

    @mcp.tool(
        description="Whether a lat/lng is inside the flood extent that applies now, the water depth there, "
        "and the distance to the edge if outside."
    )
    def flood_check_point(lat: float, lng: float) -> dict[str, Any]:
        return run(lambda conn: tools.check_point(conn, lat, lng))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="flood-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
