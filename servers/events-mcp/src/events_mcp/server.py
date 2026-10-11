"""events-mcp server. Run: `uv run --package events-mcp python -m events_mcp [--transport streamable-http --port 8119]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from events_mcp import tools

NAME = "events"
DEFAULT_PORT = 8119
INSTRUCTIONS = "Crowd events ahead and the load they put on nearby towers. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Fictional crowd events in a circle that are on now or start within within_min minutes (5-14400), soonest first, "
        "with attendance and the 5 serving towers. radius_km 0.1-100."
    )
    def events_list_upcoming(lat: float, lng: float, radius_km: float = 30.0, within_min: int = 4320) -> dict[str, Any]:
        return run(lambda conn: tools.list_upcoming(conn, lat, lng, radius_km, within_min))

    @mcp.tool(
        description="The load an event's crowd puts on the towers around the venue at its peak: baseline, uplift and predicted PRB, the "
        "risk (LOW, MEDIUM at 70%, HIGH at 85%) and the subscribers affected."
    )
    def events_forecast_load(event_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.forecast_load(conn, event_id))

    @mcp.tool(
        description="Recommended preparations for an event as data: what to do, on which towers, and the tool an agent would call "
        "next (twin_simulate_tilt, exposure_quote, care_draft_notice, energy_find_savings). Nothing is executed."
    )
    def events_capacity_plan(event_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.capacity_plan(conn, event_id))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="events-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
