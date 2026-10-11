"""The demo web app: serves one page and relays tool calls to the MCP servers. Demo only, all data synthetic.

The browser composes the calls (circle search, subscriber lists, trails). The servers are still never called by each
other. For the Story tab the app holds the model key and the approver key server-side only: they never reach the
browser or the servers, and only a human pressing Approve can trigger an approval.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from menara_agent.loop import ChatClient
from menara_agent.tools import HIDDEN_TOOLS, ToolInfo
from menara_core import clock, settings
from menara_core.db import connect
from menara_core.reset import reset_runtime_state
from menara_core.scenario import load_scenario
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from menara_demo.app_types import Hub, HubFactory
from menara_demo.runs import RunManager
from menara_demo.trail_story import (
    DEFAULT_WINDOW_MIN,
    MAX_WINDOW_MIN,
    StoryError,
    build_facts,
    tell,
)

STATIC = Path(__file__).parent / "static"
MIN_T_MIN, MAX_T_MIN = -1440, 720  # the seeded period is -1440 to 480; a little past the end is allowed
MAX_STEPS = 80
HASH_RE = re.compile(r"^[0-9a-f]{16}$")
DEFAULT_TASK = (
    "Support ticket TK-88213 just arrived. Find the cause and the blast radius, record an Incident, request a drone "
    "inspection of the failed tower and report what it finds. Then relieve the overloaded neighbour towers with a "
    "tilt: simulate first, apply it through policy, verify with KPIs, and roll back if it does not help."
)
NO_KEY = "No model key: put DEEPSEEK_API_KEY in the .env file at the repo root, then restart the demo. Replay works without it."


def _bad(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


async def _json_body(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError:
        return None


def _int_in(value: Any, low: int, high: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def create_app(
    hub_factory: HubFactory,
    db_file: Path,
    *,
    llm: ChatClient | None = None,
    approver_key: str = "",
    model_name: str | None = None,
) -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with hub_factory() as hub:
            app.state.hub = hub
            app.state.runs = RunManager(hub, db_file, llm, approver_key)
            yield

    def visible_tools(request: Request) -> list[ToolInfo]:
        hub: Hub = request.app.state.hub
        return [tool for tool in hub.tools if tool.name not in HIDDEN_TOOLS]

    def runs(request: Request) -> RunManager:
        manager: RunManager = request.app.state.runs
        return manager

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

    def read_clock_body() -> dict[str, Any]:
        conn = connect(db_file)
        try:
            return {"t_min": clock.now_min(conn), "as_of": clock.as_of(conn)}
        finally:
            conn.close()

    def read_clock() -> JSONResponse:
        return JSONResponse(read_clock_body())

    async def clock_route(request: Request) -> Response:
        if request.method == "GET":
            return read_clock()
        body = await _json_body(request)
        value = body.get("t_min") if isinstance(body, dict) else None
        if not isinstance(value, int) or not _int_in(value, MIN_T_MIN, MAX_T_MIN):
            return _bad(f"t_min must be an integer from {MIN_T_MIN} to {MAX_T_MIN}")
        writer = connect(db_file, owned_tables={"scenario_state"})
        try:
            clock.set_now(writer, value)
        finally:
            writer.close()
        return read_clock()

    async def trail_story(request: Request) -> Response:
        body = await _json_body(request)
        digest = body.get("msisdn_hash") if isinstance(body, dict) else None
        window = body.get("window_min", DEFAULT_WINDOW_MIN) if isinstance(body, dict) else None
        if not isinstance(digest, str) or not HASH_RE.match(digest):
            return _bad("msisdn_hash must be 16 hex characters")
        if not isinstance(window, int) or not _int_in(window, 5, MAX_WINDOW_MIN):
            return _bad(f"window_min must be an integer from 5 to {MAX_WINDOW_MIN}")
        if llm is None:
            return _bad(NO_KEY, 503)
        try:
            facts = await build_facts(request.app.state.hub, digest, window)
        except StoryError as error:
            return _bad(str(error), error.status)
        try:
            story = await tell(llm, facts)
        except Exception as error:
            return _bad(f"The model could not write the story: {error}", 502)
        return JSONResponse({"ok": True, "story": story, "facts": facts, "routines": facts["routines"], "model": model_name})

    async def trail_routines(request: Request) -> Response:
        digest = request.query_params.get("msisdn_hash")
        raw = request.query_params.get("window_min", str(DEFAULT_WINDOW_MIN))
        if digest is None or not HASH_RE.match(digest):
            return _bad("msisdn_hash must be 16 hex characters")
        if not raw.isdigit() or not _int_in(int(raw), 5, MAX_WINDOW_MIN):
            return _bad(f"window_min must be an integer from 5 to {MAX_WINDOW_MIN}")
        try:
            facts = await build_facts(request.app.state.hub, digest, int(raw))
        except StoryError as error:
            return _bad(str(error), error.status)
        return JSONResponse({"ok": True, "facts": facts, "routines": facts["routines"]})

    async def agent_status(request: Request) -> Response:
        return JSONResponse(
            {
                "live_available": llm is not None,
                "model": model_name if llm is not None else None,
                "running": runs(request).running,
            }
        )

    async def agent_run(request: Request) -> Response:
        body = await _json_body(request)
        if not isinstance(body, dict):
            return _bad("Send JSON like {\"mode\": \"live\", \"task\": \"...\"}")
        mode = body.get("mode")
        if mode not in {"live", "replay"}:
            return _bad("mode must be live or replay")
        task = body.get("task", DEFAULT_TASK if mode == "replay" else None)
        if not isinstance(task, str) or not task.strip():
            return _bad("task must be a non-empty string")
        start = body.get("clock", 12)
        if not _int_in(start, MIN_T_MIN, MAX_T_MIN):
            return _bad(f"clock must be an integer from {MIN_T_MIN} to {MAX_T_MIN}")
        steps = body.get("max_steps", 40)
        if not _int_in(steps, 1, MAX_STEPS):
            return _bad(f"max_steps must be an integer from 1 to {MAX_STEPS}")
        if mode == "live" and llm is None:
            return _bad(NO_KEY, 503)
        manager = runs(request)
        if manager.running:
            return _bad("A run is already in progress. Cancel it or wait for it to finish.", 409)
        return JSONResponse({"ok": True, "run_id": manager.start(mode, task.strip(), start, steps)})

    async def agent_events(request: Request) -> Response:
        manager = runs(request)
        try:
            since = int(request.query_params.get("since", "0"))
        except ValueError:
            return _bad("since must be an integer")
        return JSONResponse(
            {
                "run_id": manager.run_id,
                "status": manager.status,
                "events": manager.events_since(since),
                "next": len(manager.events),
                "pending_approval": manager.pending_approval,
            }
        )

    async def agent_decision(request: Request) -> Response:
        body = await _json_body(request)
        approve = body.get("approve") if isinstance(body, dict) else None
        if not isinstance(approve, bool):
            return _bad("Send {\"approve\": true} or {\"approve\": false}")
        if not runs(request).decide(approve):
            return _bad("Nothing is waiting for a decision", 409)
        return JSONResponse({"ok": True})

    async def reset(request: Request) -> Response:
        manager = runs(request)
        if manager.running:
            return _bad("A run is in progress: cancel it first.", 409)
        scenario = load_scenario(settings.default_scenario_path())
        deleted = reset_runtime_state(db_file, scenario)
        manager.clear()
        return JSONResponse({"ok": True, "deleted": deleted, "clock": read_clock_body()})

    async def agent_cancel(request: Request) -> Response:
        if not runs(request).cancel():
            return _bad("No run is in progress", 409)
        return JSONResponse({"ok": True})

    return Starlette(
        routes=[
            Route("/", index),
            Route("/api/tools", tools),
            Route("/api/call", call, methods=["POST"]),
            Route("/api/clock", clock_route, methods=["GET", "POST"]),
            Route("/api/trail/story", trail_story, methods=["POST"]),
            Route("/api/trail/routines", trail_routines),
            Route("/api/agent/status", agent_status),
            Route("/api/agent/run", agent_run, methods=["POST"]),
            Route("/api/agent/events", agent_events),
            Route("/api/agent/decision", agent_decision, methods=["POST"]),
            Route("/api/agent/cancel", agent_cancel, methods=["POST"]),
            Route("/api/reset", reset, methods=["POST"]),
        ],
        lifespan=lifespan,
    )