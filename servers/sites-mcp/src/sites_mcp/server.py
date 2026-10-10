"""sites-mcp server. Run: `uv run --package sites-mcp python -m sites_mcp [--transport streamable-http --port 8112]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from sites_mcp import tools

NAME = "sites"
DEFAULT_PORT = 8112
INSTRUCTIONS = (
    "Critical sites (hospitals, clinics, police, schools, SLA enterprise customers) and the tower serving each. "
    "ALL DATA IS SYNTHETIC; names are fictional. Read-only. emergency_service sites must never be changed "
    "without human approval. Every response has evidence[] naming the call that produced it."
)


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(description="One critical site: kind, location, priority, emergency_service, SLA flag and serving tower.")
    def sites_get_site(critical_site_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_site(conn, critical_site_id))

    @mcp.tool(
        description="Critical sites inside a lat/lng bounding box, highest priority first. "
        "kind filter: HOSPITAL, CLINIC, POLICE, FIRE, SCHOOL or ENTERPRISE."
    )
    def sites_list_in_bbox(
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        kind: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        return run(lambda conn: tools.list_in_bbox(conn, min_lat, min_lng, max_lat, max_lng, kind, limit))

    @mcp.tool(
        description="Critical sites served by one tower, with counts by kind, "
        "the number of emergency-service sites and SLA customers."
    )
    def sites_for_tower(enodeb_name: str) -> dict[str, Any]:
        return run(lambda conn: tools.sites_for_tower(conn, enodeb_name))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sites-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
