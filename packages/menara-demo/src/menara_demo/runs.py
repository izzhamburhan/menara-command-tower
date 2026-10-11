"""One agent run at a time for the Story tab: live (a model decides) or replay (a fixed script decides).

Every tool call goes through the same stack as the terminal driver: the human-approval gate, then the demo clock
tool, then the real MCP servers. Events are appended to a list that the page polls. Nothing secret is ever put in
an event: the approver key stays inside the gate, and the model key stays inside the model client.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

from menara_agent.cli import DEMO_CLOCK_TOOL, ClockRunner
from menara_agent.gate import GatedRunner
from menara_agent.loop import ChatClient, ToolRunner, run_agent
from menara_agent.tools import to_openai_tool, visible
from menara_core import clock
from menara_core.db import connect

from menara_demo.app_types import Hub
from menara_demo.map_effects import Effect, effects_for


class _Cancellable:
    """Stops a cancelled run at its next tool call."""

    def __init__(self, inner: ToolRunner, is_cancelled: Any) -> None:
        self._inner = inner
        self._is_cancelled = is_cancelled

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        if self._is_cancelled():
            raise asyncio.CancelledError
        return await self._inner.call(name, arguments)


class _Mapper:
    """Works out map effects from each tool's full result (the result event only carries shortened text)."""

    def __init__(self, inner: ToolRunner, db_file: Path, effects: dict[int, list[Effect]]) -> None:
        self._inner = inner
        self._db_file = db_file
        self._effects = effects
        self._step = 0

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self._step += 1
        step = self._step
        text = await self._inner.call(name, arguments)
        try:
            found = effects_for(self._db_file, name, arguments, text)
        except Exception:
            found = []
        if found:
            self._effects[step] = found
        return text


class RunManager:
    def __init__(self, hub: Hub, db_file: Path, llm: ChatClient | None, approver_key: str) -> None:
        self._hub = hub
        self._db_file = db_file
        self._llm = llm
        self._approver_key = approver_key
        self.run_id: str | None = None
        self.status = "idle"
        self.events: list[dict[str, Any]] = []
        self._pending: asyncio.Future[bool] | None = None
        self._pending_summary: str | None = None
        self._cancelled = False
        self._task: asyncio.Task[None] | None = None
        self._effects: dict[int, list[Effect]] = {}

    @property
    def running(self) -> bool:
        return self.status == "running"

    @property
    def pending_approval(self) -> str | None:
        return self._pending_summary if self._pending is not None else None

    def start(self, mode: str, task: str, clock_min: int, max_steps: int) -> str:
        model: ChatClient
        if mode == "replay":
            from menara_demo.scripted import ReplayModel

            model = ReplayModel()
        else:
            assert self._llm is not None
            model = self._llm
        writer = connect(self._db_file, owned_tables={"scenario_state"})
        try:
            clock.set_now(writer, clock_min)
        finally:
            writer.close()
        self.run_id = uuid.uuid4().hex[:8]
        self.status = "running"
        self.events = []
        self._cancelled = False
        self._pending = None
        self._pending_summary = None
        self._effects = {}
        self._task = asyncio.create_task(self._run(model, task, max_steps))
        return self.run_id

    def clear(self) -> None:
        """Forget the last run so the page starts empty. Not while a run is in progress."""
        if self.running:
            raise RuntimeError("A run is in progress")
        self.run_id = None
        self.status = "idle"
        self.events = []
        self._pending = None
        self._pending_summary = None
        self._effects = {}
        self._cancelled = False
        self._task = None

    def events_since(self, since: int) -> list[dict[str, Any]]:
        return self.events[max(0, since) :]

    def decide(self, approve: bool) -> bool:
        if self._pending is None or self._pending.done():
            return False
        self.events.append({"type": "decision", "approved": approve})
        self._pending.set_result(approve)
        return True

    def cancel(self) -> bool:
        if not self.running:
            return False
        self._cancelled = True
        if self._pending is not None and not self._pending.done():
            self.events.append({"type": "decision", "approved": False, "cancelled": True})
            self._pending.set_result(False)
        return True

    async def _ask_human(self, summary: str) -> bool:
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        self._pending_summary = summary
        self.events.append({"type": "approval", "summary": summary})
        try:
            return await self._pending
        finally:
            self._pending = None
            self._pending_summary = None

    def _on_event(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        if event.get("type") == "result" and event.get("ok"):
            found = self._effects.pop(int(event["step"]), None)
            if found:
                self.events.append({"type": "map", "step": event["step"], "effects": found})

    async def _run(self, model: ChatClient, task: str, max_steps: int) -> None:
        runner = _Mapper(
            _Cancellable(
                ClockRunner(GatedRunner(self._hub, self._approver_key, self._ask_human), self._db_file),
                lambda: self._cancelled,
            ),
            self._db_file,
            self._effects,
        )
        tools = [to_openai_tool(t) for t in visible(self._hub.tools)] + [DEMO_CLOCK_TOOL]
        try:
            text = await run_agent(model, runner, task, tools, max_steps, log=lambda _: None, on_event=self._on_event)
            status = "cancelled" if self._cancelled else "done"
        except asyncio.CancelledError:
            text, status = "Run cancelled.", "cancelled"
        except Exception as error:
            text, status = f"{type(error).__name__}: {error}".rstrip(": "), "error"
        self.events.append({"type": "final", "status": status, "text": text})
        self.status = status