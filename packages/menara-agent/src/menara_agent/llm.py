"""DeepSeek through its OpenAI-compatible API."""

from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from menara_agent.config import Settings
from menara_agent.loop import SYSTEM_PROMPT, Reply, ToolCall


def parse_reply(message: Any) -> Reply:
    calls: list[ToolCall] = []
    for call in message.tool_calls or []:
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            arguments = {}  # the tool will reject the missing arguments and the model sees that error
        calls.append(ToolCall(call.id, call.function.name, arguments if isinstance(arguments, dict) else {}))
    return Reply(content=message.content, tool_calls=calls)


class DeepSeekClient:
    def __init__(self, settings: Settings) -> None:
        self._model = settings.model
        self._client = AsyncOpenAI(api_key=settings.api_key, base_url=settings.base_url)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        payload: Any = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
        tool_defs: Any = tools
        response = await self._client.chat.completions.create(model=self._model, messages=payload, tools=tool_defs)
        return parse_reply(response.choices[0].message)