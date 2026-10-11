"""enterprise-mcp server. Run: `uv run --package enterprise-mcp python -m enterprise_mcp [--transport streamable-http --port 8116]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from enterprise_mcp import tools

NAME = "enterprise"
DEFAULT_PORT = 8116
INSTRUCTIONS = "Business customers, revenue and SLA penalty at risk, and service credits. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Business customers on towers that are DOWN or DEGRADED at the scenario clock: outage minutes, revenue per hour "
        "at risk, SLA penalty accrued and projected for 2 hours, credits issued, net exposure (RM). Give enodeb_names, or lat+lng+radius_km."
    )
    def enterprise_get_revenue_at_risk(
        enodeb_names: list[str] | None = None, lat: float | None = None, lng: float | None = None, radius_km: float = 15.0
    ) -> dict[str, Any]:
        return run(lambda conn: tools.get_revenue_at_risk(conn, enodeb_names, lat, lng, radius_km))

    @mcp.tool(description="Fictional business customers in a circle with their current service state (UP, DEGRADED, DOWN), nearest first. limit 1-200.")
    def enterprise_list_accounts(lat: float, lng: float, radius_km: float = 15.0, limit: int = 50) -> dict[str, Any]:
        return run(lambda conn: tools.list_accounts(conn, lat, lng, radius_km, limit))

    @mcp.tool(
        description="Issue an SLA service credit for hours (0.5-72) to an affected account (amount = hours x its penalty rate, capped at the "
        "monthly value). Moves money: needs a policy_token for action enterprise_issue_credit on the account's tower; policy always asks a human."
    )
    def enterprise_issue_credit(account_id: str, hours: float, policy_token: str, reason: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.issue_credit(conn, account_id, hours, policy_token, reason))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="enterprise-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
