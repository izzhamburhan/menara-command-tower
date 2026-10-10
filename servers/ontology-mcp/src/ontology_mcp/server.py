"""ontology-mcp server. Run: `uv run --package ontology-mcp python -m ontology_mcp [--transport streamable-http --port 8104]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from ontology_mcp import tools

NAME = "ontology"
DEFAULT_PORT = 8104
INSTRUCTIONS = (
    "Linked objects for towers: blast radius, neighbours, upstream dependencies, and Incidents. "
    "ALL DATA IS SYNTHETIC. Pass a tower as enodeb_name (KKRI-0142) or site_id (SITE-KKRI-0142). "
    "Reads other domains' tables read-only; writes only incidents (ontology_create_incident, "
    "ontology_update_incident). Every response has evidence[] naming the call that produced it."
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
        description="Blast radius of a tower: towers within radius_km (default 20), estimated subscribers, "
        "critical sites served (counts by kind, emergency-service and SLA customers) and the feeders involved."
    )
    def ontology_blast_radius(site: str, radius_km: float = 20.0, limit: int = 200) -> dict[str, Any]:
        return run(lambda conn: tools.blast_radius(conn, site, radius_km, limit))

    @mcp.tool(description="Neighbouring towers (nearest and reverse links) with status, distance and PRB load.")
    def ontology_neighbours(site: str) -> dict[str, Any]:
        return run(lambda conn: tools.neighbours(conn, site))

    @mcp.tool(
        description="What a tower depends on: its power feeder (and the towers sharing it) and the nearest river gauge."
    )
    def ontology_upstream_of(site: str) -> dict[str, Any]:
        return run(lambda conn: tools.upstream_of(conn, site))

    @mcp.tool(
        description="Create the Incident for a tower: cause (FLOOD, POWER, TRANSPORT, HARDWARE, CONFIG, UNKNOWN), "
        "confidence 0-1, summary, clustered ticket ids and evidence entries "
        "confidence 0-1, summary (5-500 characters), clustered ticket ids and evidence entries "
        "({source, tool, call_id, ref}) copied from earlier tool responses. One open incident per tower."
    )
    def ontology_create_incident(
        enodeb_name: str,
        cause: str,
        cause_confidence: float,
        summary: str,
        ticket_ids: list[str] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return run(
            lambda conn: tools.create_incident(
                conn, enodeb_name, cause, cause_confidence, summary, ticket_ids, evidence
            )
        )

    @mcp.tool(description="One incident with its tickets, evidence and notes.")
    def ontology_get_incident(incident_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_incident(conn, incident_id))

    @mcp.tool(description="Incidents, newest first. Optional status (OPEN, MITIGATING, RESOLVED) and tower filters.")
    def ontology_list_incidents(
        status: str | None = None, enodeb_name: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        return run(lambda conn: tools.list_incidents(conn, status, enodeb_name, limit))

    @mcp.tool(
        description="Move an incident forward (OPEN to MITIGATING to RESOLVED, or OPEN to RESOLVED) "
        "and optionally append a note."
        "and optionally append a note. The new status must differ from the current one and there is no way back, "
        "so it cannot be used to add a note to an incident that stays in the same state."
    )
    def ontology_update_incident(incident_id: str, status: str, note: str | None = None) -> dict[str, Any]:
        return run(lambda conn: tools.update_incident(conn, incident_id, status, note))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ontology-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()