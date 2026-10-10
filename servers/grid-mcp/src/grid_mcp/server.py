"""grid-mcp server. Run: `uv run --package grid-mcp python -m grid_mcp [--transport streamable-http --port 8106]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from grid_mcp import tools

NAME = "grid"
DEFAULT_PORT = 8106
INSTRUCTIONS = (
    "Power feeder status and outages for tower sites. ALL DATA IS SYNTHETIC. Read-only. "
    "Use grid_get_tower_power with a tower's enodeb_name to see whether its mains supply is expected. "
    "Every response has evidence[] naming the call that produced it."
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
        description="The feeder that powers a tower: status (ENERGISED, AT_RISK, TRIPPED), since when, "
        "note, restoration ETA, customers affected, and whether mains is expected."
    )
    def grid_get_tower_power(enodeb_name: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_tower_power(conn, enodeb_name))

    @mcp.tool(description="One feeder's status and the towers it supplies.")
    def grid_get_feeder_status(feeder_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_feeder_status(conn, feeder_id))

    @mcp.tool(
        description="Feeders that are tripped (and, by default, at risk) now, tripped first, "
        "with total customers affected."
    )
    def grid_list_outages(include_at_risk: bool = True) -> dict[str, Any]:
        return run(lambda conn: tools.list_outages(conn, include_at_risk))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="grid-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
