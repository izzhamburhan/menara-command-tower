"""sensors-mcp server. Run: `uv run --package sensors-mcp python -m sensors_mcp [--transport streamable-http --port 8120]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from sensors_mcp import tools

NAME = "sensors"
DEFAULT_PORT = 8120
INSTRUCTIONS = "Smart-city sensors and early-warning alerts. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Fictional smart-city sensors (WATER_LEVEL, RAIN, AIR_QUALITY) in a circle with their latest reading, unit and status "
        "(OK, WARNING, DANGER), nearest first. radius_km 0.1-100; kind filters. Read-only."
    )
    def sensors_list_in_area(lat: float, lng: float, radius_km: float = 20.0, kind: str | None = None) -> dict[str, Any]:
        return run(lambda conn: tools.list_in_area(conn, lat, lng, radius_km, kind))

    @mcp.tool(description="One sensor's readings over the last window_min minutes (5-1440), up to the scenario clock, with the latest, min and max.")
    def sensors_get_readings(sensor_id: str, window_min: int = 360) -> dict[str, Any]:
        return run(lambda conn: tools.get_readings(conn, sensor_id, window_min))

    @mcp.tool(
        description="Early warning: sensors over their warning level in a circle, most urgent first, with the trend per hour and the projected "
        "minutes to the danger level (0 when already past it, null when steady or falling). The Kuala Krai water sensors alert at T0."
    )
    def sensors_get_alerts(lat: float, lng: float, radius_km: float = 20.0, kind: str | None = None) -> dict[str, Any]:
        return run(lambda conn: tools.get_alerts(conn, lat, lng, radius_km, kind))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sensors-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
