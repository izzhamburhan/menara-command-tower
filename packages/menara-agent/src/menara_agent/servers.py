"""Start the MCP servers from .mcp.json as stdio subprocesses and expose their tools to the loop."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent

from menara_agent.tools import ToolInfo

# Never handed to a server subprocess. The agent key is only for the model API; the approver key is human-only.
SECRET_VARS = frozenset({"DEEPSEEK_API_KEY", "MENARA_APPROVER_KEY"})


@dataclass(frozen=True)
class ServerSpec:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


def scrubbed_env(source: Mapping[str, str] | None = None) -> dict[str, str]:
    return {k: v for k, v in (os.environ if source is None else source).items() if k not in SECRET_VARS}


def load_config(path: Path) -> dict[str, ServerSpec]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    servers: dict[str, Any] = raw["mcpServers"]
    return {
        name: ServerSpec(entry["command"], list(entry.get("args", [])), dict(entry.get("env", {})))
        for name, entry in servers.items()
    }


class McpHub:
    """All servers behind one `call(name, arguments)`; tool names are unique because they are domain-prefixed."""

    def __init__(self, specs: dict[str, ServerSpec], cwd: Path | None = None) -> None:
        self._specs = specs
        self._cwd = cwd
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self.tools: list[ToolInfo] = []

    async def __aenter__(self) -> McpHub:
        try:
            for server, spec in self._specs.items():
                params = StdioServerParameters(
                    command=spec.command,
                    args=spec.args,
                    env={**scrubbed_env(), **spec.env},
                    cwd=self._cwd,
                )
                read, write = await self._stack.enter_async_context(stdio_client(params))
                session = await self._stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                for tool in (await session.list_tools()).tools:
                    if tool.name in self._sessions:
                        raise ValueError(f"Duplicate tool name {tool.name!r} (second one from {server})")
                    self._sessions[tool.name] = session
                    self.tools.append(ToolInfo(tool.name, tool.description, tool.inputSchema))
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self._stack.aclose()

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._sessions[name].call_tool(name, arguments)
        text = "\n".join(block.text for block in result.content if isinstance(block, TextContent))
        if result.isError:
            raise RuntimeError(text or f"{name} failed")
        return text