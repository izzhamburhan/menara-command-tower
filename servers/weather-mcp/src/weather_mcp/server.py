"""weather-mcp server. Run: `uv run --package weather-mcp python -m weather_mcp [--transport streamable-http --port 8105]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from weather_mcp import tools

NAME = "weather"
DEFAULT_PORT = 8105
INSTRUCTIONS = (
    "Rainfall and lightning near a location (lat/lng, for example a tower's). ALL DATA IS SYNTHETIC. "
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
        description="Rainfall near a lat/lng from the nearest weather station within radius_km: window total, "
        "last hour, peak, 24 h total and an intensity label (NORMAL, HEAVY, VERY_HEAVY, EXTREME), plus hourly points."
    )
    def weather_get_rainfall(
        lat: float, lng: float, window_min: int = 1440, radius_km: float = 30.0
    ) -> dict[str, Any]:
        return run(lambda conn: tools.get_rainfall(conn, lat, lng, window_min, radius_km))

    @mcp.tool(
        description="Lightning strikes near a lat/lng from the nearest station: window total, last hour, peak "
        "and an activity label (NONE, LOW, HIGH, SEVERE)."
    )
    def weather_get_lightning(
        lat: float, lng: float, window_min: int = 60, radius_km: float = 30.0
    ) -> dict[str, Any]:
        return run(lambda conn: tools.get_lightning(conn, lat, lng, window_min, radius_km))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="weather-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
