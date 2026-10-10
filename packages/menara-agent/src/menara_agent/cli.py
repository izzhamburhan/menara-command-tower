"""`uv run python -m menara_agent "<task>"`: drive the Menara MCP servers with DeepSeek."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from menara_core import clock, settings
from menara_core.db import connect

from menara_agent.config import SettingsError, load_dotenv, load_settings
from menara_agent.gate import GatedRunner
from menara_agent.llm import DeepSeekClient
from menara_agent.loop import ChatClient, ToolRunner, run_agent
from menara_agent.servers import SECRET_VARS, McpHub, ServerSpec, load_config
from menara_agent.tools import to_openai_tool, visible

MAX_ADVANCE_MIN = 1440
DEMO_CLOCK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "demo_advance_clock",
        "description": (
            "DEMO ONLY. Moves the synthetic scenario clock forward by N minutes so slow things, such as a drone "
            "inspection, can finish. Use it only to wait for something you have already started."
        ),
        "parameters": {
            "type": "object",
            "properties": {"minutes": {"type": "integer", "description": f"1 to {MAX_ADVANCE_MIN}"}},
            "required": ["minutes"],
        },
    },
}


class ClockRunner:
    """Handles demo_advance_clock itself; everything else goes to the wrapped runner."""

    def __init__(self, inner: ToolRunner, db_file: Path) -> None:
        self._inner = inner
        self._db_file = db_file

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name != "demo_advance_clock":
            return await self._inner.call(name, arguments)
        minutes = arguments.get("minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or not 1 <= minutes <= MAX_ADVANCE_MIN:
            raise ValueError(f"minutes must be an integer from 1 to {MAX_ADVANCE_MIN}")
        conn = connect(self._db_file, owned_tables={"scenario_state"})
        try:
            clock.set_now(conn, clock.now_min(conn) + minutes)
            return json.dumps({"t_min": clock.now_min(conn), "as_of": clock.as_of(conn), "synthetic": True})
        finally:
            conn.close()


def _human_says_yes(summary: str) -> bool:
    print(f"\n*** HUMAN APPROVAL NEEDED ***\n{summary}")
    try:
        return input("Approve? [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:  # no terminal to ask: the answer is no
        return False


def main(
    argv: list[str] | None = None,
    *,
    llm: ChatClient | None = None,
    specs: dict[str, ServerSpec] | None = None,
    ask_human: Callable[[str], bool] = _human_says_yes,
) -> int:
    parser = argparse.ArgumentParser(prog="menara-agent", description=__doc__)
    parser.add_argument("task", help="what to ask the agent, e.g. 'Ticket TK-88213 arrived. Investigate.'")
    parser.add_argument("--clock", type=int, default=12, help="scenario minute to start at (default 12: storm complete)")
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--servers", default=None, help="comma-separated subset of servers (default: all)")
    parser.add_argument("--mcp-config", type=Path, default=None, help="default: <repo>/.mcp.json")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # model output has arrows and quotes; the Windows default codec cannot print them
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    root = settings.repo_root()
    dotenv = load_dotenv(root / ".env")
    env = {**dotenv, **os.environ}
    if llm is None:
        try:
            llm = DeepSeekClient(load_settings(env))
        except SettingsError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    chosen = specs if specs is not None else load_config(args.mcp_config or root / ".mcp.json")
    if args.servers:
        wanted = {name.strip() for name in args.servers.split(",")}
        chosen = {name: spec for name, spec in chosen.items() if name in wanted}
    # Servers need shared dev settings from .env (the signing key), never the secrets.
    shared = {k: v for k, v in dotenv.items() if k not in SECRET_VARS}
    chosen = {name: dataclasses.replace(spec, env={**shared, **spec.env}) for name, spec in chosen.items()}

    db_file = settings.db_path()
    writer = connect(db_file, owned_tables={"scenario_state"})
    clock.set_now(writer, args.clock)
    writer.close()

    approver_key = env.get("MENARA_APPROVER_KEY") or settings.approver_key()
    return asyncio.run(_run(llm, chosen, root, db_file, approver_key, ask_human, args.task, args.max_steps))


async def _run(
    llm: ChatClient,
    specs: dict[str, ServerSpec],
    root: Path,
    db_file: Path,
    approver_key: str,
    ask_human: Callable[[str], bool],
    task: str,
    max_steps: int,
) -> int:
    async with McpHub(specs, cwd=root) as hub:
        runner = ClockRunner(GatedRunner(hub, approver_key, ask_human), db_file)
        tools = [to_openai_tool(tool) for tool in visible(hub.tools)] + [DEMO_CLOCK_TOOL]
        final = await run_agent(llm, runner, task, tools, max_steps)
    print(f"\n=== Final answer ===\n{final}")
    return 0