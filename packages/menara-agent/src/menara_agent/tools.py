"""Tool definitions the model sees: MCP schemas converted to the OpenAI function format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The human approves or rejects in the terminal; the model must never hold these.
HIDDEN_TOOLS = frozenset({"policy_approve", "policy_reject", "policy_update_setting", "policy_set_kill_switch"})


@dataclass(frozen=True)
class ToolInfo:
    name: str
    description: str | None
    input_schema: dict[str, Any]


def to_openai_tool(tool: ToolInfo) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": tool.name, "description": tool.description or "", "parameters": tool.input_schema},
    }


def visible(tools: list[ToolInfo]) -> list[ToolInfo]:
    return [tool for tool in tools if tool.name not in HIDDEN_TOOLS]