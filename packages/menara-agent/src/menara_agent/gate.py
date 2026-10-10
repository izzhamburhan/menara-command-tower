"""Human approval gate.

Wraps a ToolRunner so that the model can ask policy-mcp for permission but can never grant it.
When policy answers "ask", the human decides in the terminal and this runner, not the model, calls
policy_approve or policy_reject with the approver key.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from menara_agent.loop import ToolRunner
from menara_agent.tools import HIDDEN_TOOLS

HUMAN = "terminal-human"


class GatedRunner:
    def __init__(self, inner: ToolRunner, approver_key: str, ask_human: Callable[[str], bool]) -> None:
        self._inner = inner
        self._approver_key = approver_key
        self._ask_human = ask_human

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name in HIDDEN_TOOLS:
            raise PermissionError(f"{name} is reserved for the human approver and is not available to the agent")
        result = await self._inner.call(name, arguments)
        if name != "policy_check_action":
            return result
        data = _data(result)
        if data.get("decision") != "ask" or not data.get("approval_id"):
            return result
        return await self._decide(str(data["approval_id"]), arguments, data)

    async def _decide(self, approval_id: str, arguments: dict[str, Any], data: dict[str, Any]) -> str:
        summary = (
            f"Approval {approval_id}: {arguments.get('action')} on {arguments.get('targets')} "
            f"(confidence {arguments.get('confidence')}). Policy says: {data.get('reason')}"
        )
        if not self._ask_human(summary):
            await self._inner.call(
                "policy_reject",
                {"approval_id": approval_id, "approver": HUMAN, "approver_key": self._approver_key},
            )
            return json.dumps({"decision": "rejected_by_human", "approval_id": approval_id})
        approved = await self._inner.call(
            "policy_approve",
            {"approval_id": approval_id, "approver": HUMAN, "approver_key": self._approver_key},
        )
        token = _data(approved).get("token")
        return json.dumps({"decision": "approved_by_human", "approval_id": approval_id, "token": token})


def _data(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}