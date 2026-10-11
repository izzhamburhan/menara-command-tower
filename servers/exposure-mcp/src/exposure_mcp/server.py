"""exposure-mcp server. Run: `uv run --package exposure-mcp python -m exposure_mcp [--transport streamable-http --port 8117]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from exposure_mcp import tools

NAME = "exposure"
DEFAULT_PORT = 8117
INSTRUCTIONS = "Quality on demand: profiles, a feasibility quote and a booking. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(description="The quality-on-demand profiles: what is guaranteed, the capacity (PRB points) a booking reserves per tower and the price (RM per hour per tower). Synthetic.")
    def exposure_list_profiles() -> dict[str, Any]:
        return run(tools.list_profiles)

    @mcp.tool(
        description="Can these towers (1-20) be sold a profile for duration_min (15-720) starting start_in_min (0-4320) from now? Per tower: spare "
        "capacity after current load, a crowd event in the window and earlier bookings; the quote in RM. Nothing is written."
    )
    def exposure_quote(profile_id: str, enodeb_names: list[str], duration_min: int, start_in_min: int = 0) -> dict[str, Any]:
        return run(lambda conn: tools.quote(conn, profile_id, enodeb_names, duration_min, start_in_min))

    @mcp.tool(
        description="Book a profile on these towers for a fictional customer name (3-60 characters). Sells a service: needs a policy_token for "
        "action exposure_book_qod on exactly these towers; policy always asks a human. Every tower must be feasible. Writes the booking log."
    )
    def exposure_book(
        profile_id: str, enodeb_names: list[str], duration_min: int, customer: str, policy_token: str, reason: str = "", start_in_min: int = 0
    ) -> dict[str, Any]:
        return run(lambda conn: tools.book(conn, profile_id, enodeb_names, duration_min, customer, policy_token, reason, start_in_min))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="exposure-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
