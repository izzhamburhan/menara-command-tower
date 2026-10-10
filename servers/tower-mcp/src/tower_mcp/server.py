"""tower-mcp server.

Run: `uv run --package tower-mcp python -m tower_mcp [--transport streamable-http --port 8101]`
Data source: synthetic SQLite by default; `--source http --api-url URL` reads a Tower API v1 service instead.
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.envelope import Envelope

from tower_mcp import tools
from tower_mcp.source import SourceFactory, TowerSource
from tower_mcp.source_http import HttpSourceFactory
from tower_mcp.source_sqlite import SqliteSourceFactory

NAME = "tower"
DEFAULT_PORT = 8101
COMMON = (
    "Cell tower status, KPIs, alarms and neighbours for Malaysia. Read-only. "
    "Keys: enodeb_name (e.g. KKRI-0142), site_id (SITE-KKRI-0142). "
    "Every response has evidence[] naming the call that produced it."
)
SYNTHETIC_NOTE = "ALL DATA IS SYNTHETIC."
LIVE_NOTE = "Data comes from a live tower API; responses are marked synthetic: false."


def build_server(open_source: SourceFactory, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    note = SYNTHETIC_NOTE if open_source.synthetic else LIVE_NOTE
    mcp = FastMCP(NAME, instructions=f"{COMMON} {note}", host=host, port=port)

    def run(call: Callable[[TowerSource], Envelope[Any]]) -> dict[str, Any]:
        with open_source() as source:
            return call(source).model_dump(mode="json")

    @mcp.tool(description="Status, attributes, cells, active alarm count, latest KPI and neighbours of one tower.")
    def tower_get_status(enodeb_name: str) -> dict[str, Any]:
        return run(lambda source: tools.get_status(source, enodeb_name))

    @mcp.tool(
        description="List towers inside a lat/lng bounding box with their status. "
        "status filter: UP, DEGRADED, DOWN or UNKNOWN."
    )
    def tower_list_in_bbox(
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        status: str | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        return run(lambda source: tools.list_in_bbox(source, min_lat, min_lng, max_lat, max_lng, status, limit))

    @mcp.tool(description="KPI samples (PRB utilisation %, drop rate %, throughput Mbps) over the last window_min minutes.")
    def tower_get_kpi(enodeb_name: str, window_min: int = 60) -> dict[str, Any]:
        return run(lambda source: tools.get_kpi(source, enodeb_name, window_min))

    @mcp.tool(description="Alarms, most severe first. Optional tower and severity filters; active only by default.")
    def tower_get_alarms(
        enodeb_name: str | None = None,
        severity: str | None = None,
        active_only: bool = True,
        limit: int = 200,
    ) -> dict[str, Any]:
        return run(lambda source: tools.get_alarms(source, enodeb_name, severity, active_only, limit))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tower-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--source",
        choices=["sqlite", "http"],
        default=os.environ.get("MENARA_TOWER_SOURCE", "sqlite"),
        help="data source (env MENARA_TOWER_SOURCE); sqlite is the synthetic dataset",
    )
    parser.add_argument("--db", type=Path, default=None, help="SQLite file for --source sqlite")
    parser.add_argument(
        "--api-url",
        default=os.environ.get("MENARA_TOWER_API_URL"),
        help="base URL of a Tower API v1 service for --source http (env MENARA_TOWER_API_URL); "
        "bearer token from MENARA_TOWER_API_TOKEN",
    )
    args = parser.parse_args(argv)
    factory: SourceFactory
    if args.source == "http":
        if not args.api_url:
            parser.error("--source http needs --api-url (or MENARA_TOWER_API_URL)")
        factory = HttpSourceFactory(args.api_url, os.environ.get("MENARA_TOWER_API_TOKEN"))
    else:
        factory = SqliteSourceFactory(args.db or settings.db_path())
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(factory, host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()