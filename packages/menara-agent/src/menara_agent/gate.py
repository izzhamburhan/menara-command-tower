"""Human approval gate.

Wraps a ToolRunner so that the model can ask policy-mcp for permission but can never grant it.
When policy answers "ask", the human decides in the terminal and this runner, not the model, calls
policy_approve or policy_reject with the approver key.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable
from difflib import SequenceMatcher
from typing import Any

from menara_agent.loop import ToolRunner
from menara_agent.tools import HIDDEN_TOOLS

HUMAN = "terminal-human"
TOKEN_SIMILARITY = 0.9


class GatedRunner:
    def __init__(self, inner: ToolRunner, approver_key: str, ask_human: Callable[[str], bool | Awaitable[bool]]) -> None:
        self._inner = inner
        self._approver_key = approver_key
        self._ask_human = ask_human
        self._tokens: list[str] = []  # tokens policy-mcp issued, so a garbled copy can be repaired

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name in HIDDEN_TOOLS:
            raise PermissionError(f"{name} is reserved for the human approver and is not available to the agent")
        result = await self._inner.call(name, self._repair_token(arguments))
        if name != "policy_check_action":
            return result
        data = _data(result)
        self._remember(data.get("token"))
        if data.get("decision") != "ask" or not data.get("approval_id"):
            return result
        return await self._decide(str(data["approval_id"]), arguments, data)

    def _remember(self, token: Any) -> None:
        if isinstance(token, str) and token and token not in self._tokens:
            self._tokens.append(token)

    def _repair_token(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """A model copying a 200-character token can drop or change a character. Swap in the token policy-mcp
        actually issued when the copy is nearly identical; anything else is left for the server to reject."""
        supplied = arguments.get("policy_token")
        if not isinstance(supplied, str) or supplied in self._tokens or not self._tokens:
            return arguments
        best = max(self._tokens, key=lambda t: SequenceMatcher(None, supplied, t, autojunk=False).ratio())
        if SequenceMatcher(None, supplied, best, autojunk=False).ratio() < TOKEN_SIMILARITY:
            return arguments
        print("    (runner repaired a mistyped policy_token with the one policy-mcp issued)")
        return {**arguments, "policy_token": best}

    async def _decide(self, approval_id: str, arguments: dict[str, Any], data: dict[str, Any]) -> str:
        summary = (
            f"Approval {approval_id}: {arguments.get('action')} on {arguments.get('targets')} "
            f"(confidence {arguments.get('confidence')}). Policy says: {data.get('reason')}"
        )
        answer = self._ask_human(summary)
        said_yes = await answer if inspect.isawaitable(answer) else answer
        if not said_yes:
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
        self._remember(token)
        return json.dumps({"decision": "approved_by_human", "approval_id": approval_id, "token": token})


def _data(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    return data if isinstance(data, dict) else {}