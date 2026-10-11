"""scam-mcp server. Run: `uv run --package scam-mcp python -m scam_mcp [--transport streamable-http --port 8121]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from scam_mcp import tools

NAME = "scam"
DEFAULT_PORT = 8121
INSTRUCTIONS = "Scam hotspots (counts only) and how many customers a shield would protect. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Scam patterns in a circle ranked by reports in the last window_min minutes (60-1440), with severity, blocked attempts and "
        "the trend (RISING, STEADY, FALLING). Counts only; patterns with fewer than 5 reports are withheld. Synthetic."
    )
    def scam_get_hotspots(lat: float, lng: float, radius_km: float = 30.0, window_min: int = 360) -> dict[str, Any]:
        return run(lambda conn: tools.get_hotspots(conn, lat, lng, radius_km, window_min))

    @mcp.tool(description="A scam pattern by id (SCM-01...): what it looks like (generic, no brand or number), its severity and the advice for customers.")
    def scam_get_pattern(pattern_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_pattern(conn, pattern_id))

    @mcp.tool(
        description="For a circle: the customers a scam shield would protect, the messages it would have blocked in the last day and an estimated "
        "loss avoided in RM (stated synthetic averages). Labelled an estimate."
    )
    def scam_estimate_protection(lat: float, lng: float, radius_km: float = 30.0) -> dict[str, Any]:
        return run(lambda conn: tools.estimate_protection(conn, lat, lng, radius_km))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scam-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
