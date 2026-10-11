"""care-mcp server. Run: `uv run --package care-mcp python -m care_mcp [--transport streamable-http --port 8115]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from care_mcp import tools

NAME = "care"
DEFAULT_PORT = 8115
INSTRUCTIONS = "Customer impact, drafted notices in four languages, and sending them. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Who is affected by an outage on these towers (down or degraded at the scenario clock): customers, open tickets "
        "nearby, the tickets predicted in the next hour if nobody is told, the language mix and the restoration time. Counts only."
    )
    def care_get_impact(enodeb_names: list[str]) -> dict[str, Any]:
        return run(lambda conn: tools.get_impact(conn, enodeb_names))

    @mcp.tool(
        description="Draft a customer notice (kind OUTAGE, RESTORED or DEGRADED; language ms, en, zh or ta) with the area, cause and "
        "restoration time filled in, the recipient count, SMS cost and expected ticket deflection. Nothing is sent."
    )
    def care_draft_notice(enodeb_names: list[str], kind: str = "OUTAGE", language: str = "en") -> dict[str, Any]:
        return run(lambda conn: tools.draft_notice(conn, enodeb_names, kind, language))

    @mcp.tool(
        description="Send a notice to the customers on these towers (message 20-480 characters). A real-world action: needs a policy_token "
        "for action comms_send_notice on exactly these towers; policy always asks a human. Writes the notice log (counts only)."
    )
    def care_send_notice(
        enodeb_names: list[str], language: str, message: str, policy_token: str, reason: str = "", kind: str = "OUTAGE"
    ) -> dict[str, Any]:
        return run(lambda conn: tools.send_notice(conn, enodeb_names, language, message, policy_token, reason, kind))

    @mcp.tool(description="The notices sent so far, newest first (counts only, no recipients). limit 1-200.")
    def care_list_notices(limit: int = 50) -> dict[str, Any]:
        return run(lambda conn: tools.list_notices(conn, limit))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="care-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
