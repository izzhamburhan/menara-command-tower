"""usage-mcp server. Run: `uv run --package usage-mcp python -m usage_mcp [--transport streamable-http --port 8113]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from usage_mcp import tools

NAME = "usage"
DEFAULT_PORT = 8113
INSTRUCTIONS = (
    "What people use on the internet, by circle or tower: top apps, categories, busiest hour. ALL DATA IS SYNTHETIC: invented "
    "estimates, aggregated, never per person. Read-only. Every response has evidence[] naming the call that produced it."
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
        description="What people in a circle use on the internet: apps ranked by users or by data, the category split and the "
        "busiest hour. hour 0-23 defaults to the scenario clock. radius_km 0.1-100, limit 1-20. Aggregated, never per person; "
        "areas with fewer than 5 estimated users are withheld. Synthetic estimates."
    )
    def usage_top_apps_in_area(
        lat: float, lng: float, radius_km: float = 10.0, rank_by: str = "users", hour: int | None = None, limit: int = 10
    ) -> dict[str, Any]:
        return run(lambda conn: tools.top_apps_in_area(conn, lat, lng, radius_km, rank_by, hour, limit))

    @mcp.tool(description="The same view for one tower (enodeb_name): top apps by users or data, categories, busiest hour.")
    def usage_get_tower_apps(enodeb_name: str, rank_by: str = "users", hour: int | None = None, limit: int = 10) -> dict[str, Any]:
        return run(lambda conn: tools.get_tower_apps(conn, enodeb_name, rank_by, hour, limit))

    @mcp.tool(
        description="One app's users hour by hour in a circle and its peak hour. app is an app id (tiktok) or a name (TikTok); "
        "an unknown app lists the valid ids."
    )
    def usage_app_trend(lat: float, lng: float, app: str, radius_km: float = 10.0) -> dict[str, Any]:
        return run(lambda conn: tools.app_trend(conn, lat, lng, radius_km, app))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="usage-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
