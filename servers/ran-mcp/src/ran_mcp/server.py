"""ran-mcp server. Run: `uv run --package ran-mcp python -m ran_mcp [--transport streamable-http --port 8111]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from ran_mcp import tools

NAME = "ran"
DEFAULT_PORT = 8111
INSTRUCTIONS = (
    "Sandboxed RAN changes: tilt, cell reset, rollback. ALL DATA IS SYNTHETIC; nothing real is changed. "
    "Every change needs a signed policy_token from policy-mcp for that exact action and set of towers "
    "(ran_tilt_cells, ran_reset_cell, ran_revert_tilt). Simulate with twin-mcp first, apply on a small set, "
    "then VERIFY the effect with tower KPIs and roll back if it does not help. "
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

    @mcp.tool(description="Cells of a tower with base tilt, applied tilt change and current tilt, and active changes.")
    def ran_get_config(enodeb_name: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_config(conn, enodeb_name))

    @mcp.tool(
        description="Apply tilt changes. changes is a list of {enodeb_name or cell_id, tilt_delta_deg} (positive = "
        "more downtilt, within +/-8; a tower name means all its cells). Needs a policy_token for action "
        "ran_tilt_cells on exactly these towers. Verify the KPI effect afterwards."
    )
    def ran_tilt_cells(changes: list[dict[str, Any]], policy_token: str, reason: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.tilt_cells(conn, changes, policy_token, reason))

    @mcp.tool(description="Soft-reset one cell. Needs a policy_token for action ran_reset_cell on its tower.")
    def ran_reset_cell(cell_id: str, policy_token: str, reason: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.reset_cell(conn, cell_id, policy_token, reason))

    @mcp.tool(
        description="Roll back an ACTIVE change; KPIs return to normal from now. Needs a policy_token for action "
        "ran_revert_tilt on the same towers."
    )
    def ran_revert_change(change_id: str, policy_token: str, reason: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.revert_change(conn, change_id, policy_token, reason))

    @mcp.tool(description="One change with its items, status (ACTIVE, REVERTED, COMPLETED) and who approved it.")
    def ran_get_change(change_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_change(conn, change_id))

    @mcp.tool(description="Changes, newest first. Optional status and tower filters.")
    def ran_list_changes(
        status: str | None = None, enodeb_name: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        return run(lambda conn: tools.list_changes(conn, status, enodeb_name, limit))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ran-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
