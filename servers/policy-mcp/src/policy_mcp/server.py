"""policy-mcp server. Run: `uv run --package policy-mcp python -m policy_mcp [--transport streamable-http --port 8109]`."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP
from menara_core import settings
from menara_core.db import connect
from menara_core.envelope import Envelope

from policy_mcp import tools

NAME = "policy"
DEFAULT_PORT = 8109
INSTRUCTIONS = (
    "Policy engine for real-world actions. ALL DATA IS SYNTHETIC. Call policy_check_action BEFORE any action: "
    "allow returns a signed token for the action MCP; ask opens an approval that only a human can approve "
    "(policy_approve needs the human approver key, which the agent must not have); deny means stop. "
    "Never try to approve your own request. Every response has evidence[] naming the call that produced it."
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
        description="Ask whether an action may run. action: ran_reset_cell, ran_tilt_cells, ran_revert_tilt, "
        "drone_dispatch, workforce_create_order, comms_send_notice, hardware_replace. targets: tower names or "
        "cell ids. confidence 0-1 is your own confidence in the diagnosis. Returns allow (with a token), "
        "ask (with an approval_id a human must decide) or deny, plus every rule evaluated."
    )
    def policy_check_action(
        action: str, targets: list[str], confidence: float, reason: str = ""
    ) -> dict[str, Any]:
        return run(lambda conn: tools.check_action(conn, action, targets, confidence, reason))

    @mcp.tool(description="One approval request: status (PENDING, AUTO_ALLOWED, APPROVED, REJECTED), reason and outcome.")
    def policy_get_approval(approval_id: str) -> dict[str, Any]:
        return run(lambda conn: tools.get_approval(conn, approval_id))

    @mcp.tool(description="Approval requests, newest first. Optional status filter.")
    def policy_list_approvals(status: str | None = None, limit: int = 50) -> dict[str, Any]:
        return run(lambda conn: tools.list_approvals(conn, status, limit))

    @mcp.tool(
        description="HUMAN ONLY. Approve a pending action and receive its signed token. "
        "Needs the human approver key."
    )
    def policy_approve(
        approval_id: str, approver: str, approver_key: str, note: str | None = None
    ) -> dict[str, Any]:
        return run(lambda conn: tools.approve(conn, approval_id, approver, approver_key, note))

    @mcp.tool(description="HUMAN ONLY. Reject a pending action. Needs the human approver key.")
    def policy_reject(
        approval_id: str, approver: str, approver_key: str, note: str | None = None
    ) -> dict[str, Any]:
        return run(lambda conn: tools.reject(conn, approval_id, approver, approver_key, note))

    @mcp.tool(
        description="Write the result of an approved or auto-allowed action back: SUCCEEDED, FAILED or ROLLED_BACK."
    )
    def policy_record_outcome(approval_id: str, outcome: str, detail: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.record_outcome(conn, approval_id, outcome, detail))

    @mcp.tool(
        description="Kill switch, thresholds, peak-hour flag, actions in the last hour, pending approvals "
        "and the actions the engine knows."
    )
    def policy_get_status() -> dict[str, Any]:
        return run(tools.get_status)

    @mcp.tool(
        description="Switch the kill switch. Anyone may turn it ON; turning it OFF needs the human approver key."
    )
    def policy_set_kill_switch(enabled: bool, actor: str, approver_key: str = "") -> dict[str, Any]:
        return run(lambda conn: tools.set_kill_switch(conn, enabled, actor, approver_key))

    @mcp.tool(description="HUMAN ONLY. Change a policy threshold. Needs the human approver key.")
    def policy_update_setting(key: str, value: str, actor: str, approver_key: str) -> dict[str, Any]:
        return run(lambda conn: tools.update_setting(conn, key, value, actor, approver_key))

    @mcp.tool(description="The audit log, newest first: every check, approval, rejection, outcome and kill-switch change.")
    def policy_get_audit(limit: int = 50) -> dict[str, Any]:
        return run(lambda conn: tools.get_audit(conn, limit))

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="policy-mcp", description=__doc__)
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args(argv)
    transport: Literal["stdio", "streamable-http"] = args.transport
    build_server(args.db or settings.db_path(), host=args.host, port=args.port).run(transport=transport)


if __name__ == "__main__":
    main()
