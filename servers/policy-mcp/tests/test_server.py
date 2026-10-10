from __future__ import annotations

import asyncio
from pathlib import Path

from policy_mcp.server import build_server

EXPECTED = {
    "policy_check_action",
    "policy_get_approval",
    "policy_list_approvals",
    "policy_approve",
    "policy_reject",
    "policy_record_outcome",
    "policy_get_status",
    "policy_set_kill_switch",
    "policy_update_setting",
    "policy_get_audit",
}


def test_server_registers_its_tools(db_file: Path) -> None:
    tools = asyncio.run(build_server(db_file).list_tools())
    assert {t.name for t in tools} == EXPECTED


def test_tool_call_returns_a_synthetic_envelope(db_file: Path) -> None:
    result = asyncio.run(build_server(db_file).call_tool("policy_get_status", {}))
    payload = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is True
    assert payload["data"]["kill_switch"] is False
