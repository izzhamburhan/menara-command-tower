"""energy-mcp server. Run: `uv run --package energy-mcp python -m energy_mcp [--transport streamable-http --port 8114]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from energy_mcp import tools

NAME = "energy"
DEFAULT_PORT = 8114
INSTRUCTIONS = "Tower power draw, battery and generator time, and night-time sleep savings. ALL DATA IS SYNTHETIC. Every response has evidence[] naming the call that produced it."


def build_server(db_path: Path, *, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> FastMCP:
    mcp = FastMCP(NAME, instructions=INSTRUCTIONS, host=host, port=port)

    def run(call: Callable[[Any], Envelope[Any]]) -> dict[str, Any]:
        conn = connect(db_path, owned_tables=tools.OWNED_TABLES)
        try:
            return call(conn).model_dump(mode="json")
        finally:
            conn.close()

    @mcp.tool(
        description="Power draw of one tower now, its supply (MAINS, BATTERY, GENERATOR) and how many hours the battery or "
        "generator will last. A tower on backup power is flagged. Synthetic estimates."
    )
    def energy_get_tower(enodeb_name: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_tower(conn, enodeb_name))

    @mcp.tool(
        description="Towers in a circle that can put idle capacity layers to sleep between 00:00 and 06:00, with kWh and CO2 "
        "(kg) saved and the risk. hour 0-23 defaults to the scenario clock; outside the window the list is empty. Read-only."
    )
    def energy_find_savings(lat: float, lng: float, radius_km: float = 15.0, hour: int | None = None) -> dict[str, Any]:
        return run(lambda conn: tools.find_savings(conn, lat, lng, radius_km, hour))

    @mcp.tool(
        description="Put idle capacity layers to sleep on 1-20 towers until 06:00. A real-world action: needs a policy_token for "
        "action energy_sleep_cells on exactly these towers (from policy_check_action). Writes the energy action log."
    )
    def energy_apply_sleep(enodeb_names: list[str], policy_token: str, reason: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.apply_sleep(conn, enodeb_names, policy_token, reason))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="energy-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
