"""The agent loop: model, tool calls, tool results, until the model answers or the step cap is hit."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

RESULT_EVENT_CHARS = 6000  # events are for a UI; the model always gets the full result

SYSTEM_PROMPT = (
    "You are an operations agent for a network command center. All data is synthetic demo data. "
    "Use the tools to investigate; do not guess. Before any real-world action, ask the policy tool and obey "
    "its answer: if a human must approve, wait for the result and never try to approve it yourself."
)


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Reply:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)


class ChatClient(Protocol):
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply: ...


class ToolRunner(Protocol):
    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


def _assistant_message(reply: Reply) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": reply.content}
    message["tool_calls"] = [
        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
        for c in reply.tool_calls
    ]
    return message


async def run_agent(
    llm: ChatClient,
    runner: ToolRunner,
    task: str,
    tools: list[dict[str, Any]],
    max_steps: int = 40,
    log: Callable[[str], None] = print,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> str:
    messages: list[dict[str, Any]] = [{"role": "user", "content": task}]
    steps = 0

    def emit(event: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event)

    while True:
        reply = await llm.complete(messages, tools)
        if not reply.tool_calls:
            return reply.content or ""
        messages.append(_assistant_message(reply))
        if reply.content:
            emit({"type": "say", "text": reply.content})
        for call in reply.tool_calls:
            if steps >= max_steps:
                return f"Stopped: step limit ({max_steps}) reached before the model finished."
            steps += 1
            log(f"[{steps}] {call.name}({json.dumps(call.arguments)})")
            emit({"type": "call", "step": steps, "name": call.name, "arguments": call.arguments})
            ok = True
            try:
                result = await runner.call(call.name, call.arguments)
            except Exception as error:
                result = f"ERROR: {error}"
                ok = False
            shown = result if len(result) <= RESULT_EVENT_CHARS else result[:RESULT_EVENT_CHARS] + "...[cut]"
            emit({"type": "result", "step": steps, "name": call.name, "ok": ok, "text": shown})
            log(f"    -> {result[:300]}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})