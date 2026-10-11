"""The demo's Reset: clear what a session created, only when no run is in progress. A fake hub and a fake model."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from menara_agent.loop import Reply, ToolCall
from menara_agent.tools import ToolInfo
from menara_core import clock
from menara_core.db import connect
from menara_core.reset import RUNTIME_TABLES
from menara_core.testing import build_test_db
from menara_demo.app import create_app
from starlette.testclient import TestClient

SCHEMA = {"type": "object", "properties": {}}
ASK = json.dumps({"synthetic": True, "data": {"decision": "ask", "reason": "needs a human", "approval_id": "APR-0001", "token": None}})
AT = "2026-11-14T07:12:00+08:00"


class FakeHub:
    def __init__(self) -> None:
        self.tools = [ToolInfo(n, "d", SCHEMA) for n in ("tower_get_status", "policy_check_action", "policy_approve", "policy_reject")]

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        return ASK if name == "policy_check_action" else json.dumps({"synthetic": True, "data": {"status": "DOWN"}})


class OneCall:
    """A model that asks for an approval and so keeps the run waiting for a human."""

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        call = ToolCall("c1", "policy_check_action", {"action": "drone_dispatch", "targets": ["KKRI-0142"], "confidence": 0.9})
        return Reply(None, [call]) if not any(m.get("role") == "tool" for m in messages) else Reply("done", [])


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return build_test_db(tmp_path)


@pytest.fixture
def client(db_file: Path) -> Iterator[TestClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeHub]:
        yield FakeHub()

    with TestClient(create_app(factory, db_file, llm=OneCall(), approver_key="k", model_name="fake")) as test_client:
        yield test_client


def play(db_file: Path) -> None:
    """Leave something behind, as a session does: an incident and an approval, a changed setting and a moved clock."""
    conn = connect(db_file, owned_tables={*RUNTIME_TABLES, "policy_setting", "scenario_state"})
    try:
        conn.execute(
            "INSERT INTO incident (incident_id, enodeb_name, cause, cause_confidence, summary, status, created_at, updated_at, evidence) "
            "VALUES ('INC-0001', 'KKRI-0142', 'FLOOD', 0.9, 's', 'OPEN', ?, ?, '[]')", (AT, AT)
        )
        conn.execute("INSERT INTO audit_log (at, actor, action, target, decision, detail) VALUES (?, 'agent', 'a', 't', 'ask', 'd')", (AT,))
        conn.execute("UPDATE policy_setting SET value = '1' WHERE key = 'kill_switch'")
        conn.commit()
        clock.set_now(conn, 377)
    finally:
        conn.close()


def wait_for(client: TestClient, done: Any, seconds: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + seconds
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = client.get("/api/agent/events").json()
        if done(state):
            return state
        time.sleep(0.05)
    raise AssertionError(f"timed out; last state: {state}")


def rows(db_file: Path, table: str) -> int:
    with sqlite3.connect(db_file) as raw:
        return int(raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_reset_clears_events_status_and_returns_the_counts_and_the_clock(client: TestClient, db_file: Path) -> None:
    play(db_file)
    reply = client.post("/api/reset")
    assert reply.status_code == 200
    body = reply.json()
    assert body["ok"] is True and body["deleted"]["incident"] == 1 and body["deleted"]["audit_log"] == 1 and body["clock"]["t_min"] == 0
    assert rows(db_file, "incident") == 0 and rows(db_file, "audit_log") == 0
    assert client.get("/api/clock").json()["t_min"] == 0


def test_reset_clears_a_finished_run_so_the_page_starts_empty(client: TestClient) -> None:
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    wait_for(client, lambda s: s["pending_approval"] is not None)
    client.post("/api/agent/cancel")
    wait_for(client, lambda s: s["status"] != "running")
    assert client.get("/api/agent/events").json()["events"]
    assert client.post("/api/reset").status_code == 200
    state = client.get("/api/agent/events").json()
    assert state["events"] == [] and state["status"] == "idle" and state["run_id"] is None and state["pending_approval"] is None


def test_reset_while_a_run_is_in_progress_is_409_and_changes_nothing(client: TestClient, db_file: Path) -> None:
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    wait_for(client, lambda s: s["pending_approval"] is not None)
    play(db_file)
    reply = client.post("/api/reset")
    assert reply.status_code == 409 and "run" in reply.json()["error"].lower()
    assert rows(db_file, "incident") == 1
    client.post("/api/agent/cancel")
    wait_for(client, lambda s: s["status"] != "running")
    assert client.post("/api/reset").status_code == 200


def test_reset_is_not_an_mcp_tool_and_not_in_the_console(client: TestClient) -> None:
    names = [t["name"] for t in client.get("/api/tools").json()]
    assert not [n for n in names if "reset" in n]
    assert client.post("/api/call", json={"name": "reset_runtime_state", "arguments": {}}).status_code == 404
    assert client.get("/api/reset").status_code == 405