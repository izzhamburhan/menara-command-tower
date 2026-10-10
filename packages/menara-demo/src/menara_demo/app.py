"""The demo web app: serves one page and relays tool calls to the MCP servers. Demo only, all data synthetic.

The browser composes the calls (circle search, subscriber lists, trails). The servers are still never called by each
other, and this app holds neither the approver key nor a model key.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from menara_agent.tools import HIDDEN_TOOLS, ToolInfo
from menara_core import clock
from menara_core.db import connect
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

STATIC = Path(__file__).parent / "static"
MIN_T_MIN, MAX_T_MIN = -1440, 720  # the seeded period is -1440 to 480; a little past the end is allowed


class Hub(Protocol):
    tools: list[ToolInfo]

    async def call(self, name: str, arguments: dict[str, Any]) -> str: ...


HubFactory = Callable[[], AbstractAsyncContextManager[Hub]]


def _bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        return None


def create_app(hub_factory: HubFactory, db_file: Path) -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with hub_factory() as hub:
            app.state.hub = hub
            yield

    def visible_tools(request: Request) -> list[ToolInfo]:
        hub: Hub = request.app.state.hub
        return [tool for tool in hub.tools if tool.name not in HIDDEN_TOOLS]

    async def index(_: Request) -> Response:
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    async def tools(request: Request) -> Response:
        return JSONResponse(
            [{"name": t.name, "description": t.description or "", "schema": t.input_schema} for t in visible_tools(request)]
        )

    async def call(request: Request) -> Response:
        body = await _json_body(request)
        if not isinstance(body, dict) or not isinstance(body.get("name"), str):
            return _bad("Send JSON like {\"name\": \"tower_get_status\", \"arguments\": {...}}")
        arguments = body.get("arguments", {})
        if not isinstance(arguments, dict):
            return _bad("arguments must be an object")
        name: str = body["name"]
        if name in HIDDEN_TOOLS:
            return _bad(f"{name} is reserved for the human approver and is not available here", 403)
        if name not in {t.name for t in visible_tools(request)}:
            return _bad(f"Unknown tool {name}", 404)
        started = time.perf_counter()
        try:
            raw = await request.app.state.hub.call(name, arguments)
        except Exception as error:  # a tool error is a normal outcome in a demo: show it
            return JSONResponse({"ok": False, "error": str(error)})
        try:
            result: Any = json.loads(raw)
        except ValueError:
            result = raw
        return JSONResponse({"ok": True, "result": result, "ms": round((time.perf_counter() - started) * 1000)})

    def read_clock() -> JSONResponse:
        conn = connect(db_file)
        try:
            return JSONResponse({"t_min": clock.now_min(conn), "as_of": clock.as_of(conn)})
        finally:
            conn.close()

    async def clock_route(request: Request) -> Response:
        if request.method == "GET":
            return read_clock()
        body = await _json_body(request)
        value = body.get("t_min") if isinstance(body, dict) else None
        if not isinstance(value, int) or isinstance(value, bool) or not MIN_T_MIN <= value <= MAX_T_MIN:
            return _bad(f"t_min must be an integer from {MIN_T_MIN} to {MAX_T_MIN}")
        writer = connect(db_file, owned_tables={"scenario_state"})
        try:
            clock.set_now(writer, value)
        finally:
            writer.close()
        return read_clock()

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/tools", tools),
            Route("/api/call", call, methods=["POST"]),
            Route("/api/clock", clock_route, methods=["GET", "POST"]),
        ],
        lifespan=lifespan,
    )