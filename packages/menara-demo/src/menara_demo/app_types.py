"""Types shared by the demo app modules."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from menara_agent.tools import ToolInfo


class Hub(Protocol):
    tools: list[ToolInfo]

    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


HubFactory = Callable[[], AbstractAsyncContextManager[Hub]]