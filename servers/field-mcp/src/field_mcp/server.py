"""field-mcp server. Run: `uv run --package field-mcp python -m field_mcp [--transport streamable-http --port 8118]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from field_mcp import tools

NAME = "field"
DEFAULT_PORT = 8118
INSTRUCTIONS = "Which technician to send, road or boat, parts and safety, and dispatching them. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Which technician to send to a tower for a skill (POWER, RAN, FIBRE, CIVIL): those on shift and free, ranked by ETA, "
        "with the access mode (ROAD, or BOAT when the tower is under floodwater), parts in stock at their depot and a safety note."
    )
    def field_find_crew(enodeb_name: str, skill: str) -> dict[str, Any]:
        return run(lambda conn: tools.find_crew(conn, enodeb_name, skill))

    @mcp.tool(
        description="Dispatch a technician (tech_id) to a tower with a task (3-200 characters). Commits staff: needs a policy_token for action "
        "workforce_create_order on that tower; policy always asks a human. access AUTO picks road or boat; ROAD into floodwater is refused."
    )
    def field_dispatch(
        enodeb_name: str, tech_id: str, task: str, policy_token: str, reason: str = "", skill: str = "POWER", access: str = "AUTO"
    ) -> dict[str, Any]:
        return run(lambda conn: tools.dispatch(conn, enodeb_name, tech_id, task, policy_token, reason, skill, access))

    @mcp.tool(description="Work orders so far, newest first, with a status that follows the scenario clock: EN_ROUTE, ON_SITE, DONE. limit 1-200.")
    def field_list_jobs(status: str | None = None, limit: int = 50) -> dict[str, Any]:
        return run(lambda conn: tools.list_jobs(conn, status, limit))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="field-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
