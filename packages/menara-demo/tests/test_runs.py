"""The Story tab's backend: live runs, human approval by button, cancel. A fake hub and a fake model, no network."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from menara_agent.loop import Reply, ToolCall
from menara_agent.tools import ToolInfo
from menara_core.testing import build_test_db
from menara_demo.app import create_app
from starlette.testclient import TestClient

APPROVER_KEY = "test-approver-key-never-shown"
SCHEMA = {"type": "object", "properties": {}}
ASK = json.dumps(
    {"synthetic": True, "data": {"decision": "ask", "reason": "needs a human", "approval_id": "APR-0001", "token": None}}
)


class FakeHub:
    def __init__(self) -> None:
        names = ["tower_get_status", "policy_check_action", "policy_approve", "policy_reject"]
        self.tools = [ToolInfo(n, "d", SCHEMA) for n in names]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "policy_check_action":
            return ASK
        if name == "policy_approve":
            return json.dumps({"synthetic": True, "data": {"token": "tok-human", "approved_by": "human:terminal-human"}})
        if name == "policy_reject":
            return json.dumps({"synthetic": True, "data": {"status": "REJECTED"}})
        return json.dumps({"synthetic": True, "data": {"status": "DOWN"}})


class ScriptedLLM:
    def __init__(self, replies: list[Reply]) -> None:
        self.replies = list(replies)

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        return self.replies.pop(0)


def status_call() -> Reply:
    return Reply(None, [ToolCall("c1", "tower_get_status", {"enodeb_name": "KKRI-0142"})])


def drone_check() -> Reply:
    args = {"action": "drone_dispatch", "targets": ["KKRI-0142"], "confidence": 0.9}
    return Reply(None, [ToolCall("c2", "policy_check_action", args)])


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return build_test_db(tmp_path)


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


def make_client(hub: FakeHub, db_file: Path, llm: ScriptedLLM | None) -> TestClient:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeHub]:
        yield hub

    return TestClient(create_app(factory, db_file, llm=llm, approver_key=APPROVER_KEY, model_name="fake-model"))


@pytest.fixture
def make(hub: FakeHub, db_file: Path) -> Iterator[Callable[[list[Reply] | None], TestClient]]:
    clients: list[TestClient] = []

    def build(replies: list[Reply] | None) -> TestClient:
        client = make_client(hub, db_file, ScriptedLLM(replies) if replies is not None else None)
        client.__enter__()
        clients.append(client)
        return client

    yield build
    for client in clients:
        client.__exit__(None, None, None)


def wait_for(client: TestClient, done: Callable[[dict[str, Any]], bool], seconds: float = 8.0) -> dict[str, Any]:
    deadline = time.time() + seconds
    state: dict[str, Any] = {}
    while time.time() < deadline:
        state = client.get("/api/agent/events").json()
        if done(state):
            return state
        time.sleep(0.05)
    raise AssertionError(f"timed out; last state: {state}")


def finished(state: dict[str, Any]) -> bool:
    return state["status"] != "running"


def waiting(state: dict[str, Any]) -> bool:
    return state["pending_approval"] is not None


def test_status_says_whether_the_live_model_is_available(make: Callable[[list[Reply] | None], TestClient]) -> None:
    assert make(None).get("/api/agent/status").json() == {"live_available": False, "model": None, "running": False}
    assert make([]).get("/api/agent/status").json() == {"live_available": True, "model": "fake-model", "running": False}


def test_a_live_run_without_a_model_key_is_503_with_a_reason(make: Callable[[list[Reply] | None], TestClient]) -> None:
    reply = make(None).post("/api/agent/run", json={"mode": "live", "task": "Investigate"})
    assert reply.status_code == 503 and "DEEPSEEK_API_KEY" in reply.json()["error"]


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "dream", "task": "x"},
        {"mode": "live"},
        {"mode": "live", "task": "  "},
        {"mode": "live", "task": "x", "clock": "soon"},
        {"mode": "live", "task": "x", "clock": 99999},
        {"mode": "live", "task": "x", "max_steps": 0},
        {"mode": "live", "task": "x", "max_steps": 500},
    ],
)
def test_bad_run_requests_are_400(make: Callable[[list[Reply] | None], TestClient], body: dict[str, Any]) -> None:
    assert make([]).post("/api/agent/run", json=body).status_code == 400


def test_a_live_run_streams_calls_results_and_one_final(make: Callable[[list[Reply] | None], TestClient], db_file: Path) -> None:
    client = make([Reply("Looking at the tower.", status_call().tool_calls), Reply("KKRI-0142 is down.", [])])
    started = client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    assert started.status_code == 200 and started.json()["run_id"]
    state = wait_for(client, finished)
    types = [e["type"] for e in state["events"]]
    assert types == ["say", "call", "result", "map", "heal", "final"] and state["status"] == "done"
    assert state["events"][-1]["text"] == "KKRI-0142 is down."
    assert client.get("/api/clock").json()["t_min"] == 20  # the run started the scenario clock where asked
    later = client.get("/api/agent/events", params={"since": 2}).json()
    assert [e["type"] for e in later["events"]] == ["result", "map", "heal", "final"] and later["next"] == 6


def test_the_human_approves_with_a_button_and_the_model_gets_the_token(
    make: Callable[[list[Reply] | None], TestClient], hub: FakeHub
) -> None:
    client = make([drone_check(), Reply("Approved and noted.", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Drone please"})
    state = wait_for(client, waiting)
    assert "APR-0001" in state["pending_approval"] and "drone_dispatch" in state["pending_approval"]
    assert state["events"][-1]["type"] == "approval"
    assert client.post("/api/agent/run", json={"mode": "live", "task": "again"}).status_code == 409
    assert client.post("/api/agent/decision", json={"approve": True}).status_code == 200
    state = wait_for(client, finished)
    approve = [c for c in hub.calls if c[0] == "policy_approve"]
    assert approve and approve[0][1]["approver_key"] == APPROVER_KEY
    result = [e for e in state["events"] if e["type"] == "result"][0]
    assert "approved_by_human" in result["text"] and "tok-human" in result["text"]
    assert [e["type"] for e in state["events"] if e["type"] == "decision"] == ["decision"]
    assert APPROVER_KEY not in json.dumps(state)  # the approver key never reaches the browser


def test_rejecting_calls_policy_reject(make: Callable[[list[Reply] | None], TestClient], hub: FakeHub) -> None:
    client = make([drone_check(), Reply("Stopped.", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Drone please"})
    wait_for(client, waiting)
    client.post("/api/agent/decision", json={"approve": False})
    state = wait_for(client, finished)
    assert [c[0] for c in hub.calls] == ["policy_check_action", "policy_reject"]
    assert "rejected_by_human" in [e for e in state["events"] if e["type"] == "result"][0]["text"]


def test_a_decision_with_nothing_pending_is_409(make: Callable[[list[Reply] | None], TestClient]) -> None:
    client = make([])
    assert client.post("/api/agent/decision", json={"approve": True}).status_code == 409
    assert client.post("/api/agent/decision", json={"approve": "maybe"}).status_code in {400, 409}


def test_cancel_rejects_a_pending_approval_and_frees_the_slot(
    make: Callable[[list[Reply] | None], TestClient], hub: FakeHub
) -> None:
    client = make([drone_check(), Reply("never", []), Reply("Second run done.", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Drone please"})
    wait_for(client, waiting)
    assert client.post("/api/agent/cancel").status_code == 200
    state = wait_for(client, finished)
    assert state["status"] == "cancelled" and state["events"][-1]["type"] == "final"
    assert "policy_approve" not in [c[0] for c in hub.calls]
    again = client.post("/api/agent/run", json={"mode": "live", "task": "Second"})
    assert again.status_code == 200 and wait_for(client, finished)["status"] == "done"


def test_a_model_failure_ends_the_run_with_an_error_event(make: Callable[[list[Reply] | None], TestClient]) -> None:
    client = make([])  # no replies left: the fake model raises
    client.post("/api/agent/run", json={"mode": "live", "task": "x"})
    state = wait_for(client, finished)
    assert state["status"] == "error" and state["events"][-1]["type"] == "final" and state["events"][-1]["text"]


def test_demo_advance_clock_is_handled_by_the_runner_not_the_servers(
    make: Callable[[list[Reply] | None], TestClient], hub: FakeHub
) -> None:
    wait = Reply(None, [ToolCall("c3", "demo_advance_clock", {"minutes": 30})])
    client = make([wait, Reply("Waited.", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Wait", "clock": 10})
    wait_for(client, finished)
    assert hub.calls == [] and client.get("/api/clock").json()["t_min"] == 40
    assert hub.calls == [] and client.get("/api/clock").json()["t_min"] == 40

def test_a_map_event_follows_a_result_event_with_the_same_step(make: Callable[[list[Reply] | None], TestClient]) -> None:
    client = make([status_call(), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    events = wait_for(client, finished)["events"]
    kinds = [e["type"] for e in events]
    assert kinds.index("map") == kinds.index("result") + 1
    event = next(e for e in events if e["type"] == "map")
    assert event["step"] == 1 and event["effects"][0]["kind"] == "focus" and event["effects"][0]["tone"] == "bad"
    assert "KKRI-0142" in event["effects"][0]["label"]


def test_a_failing_effect_builder_does_not_break_the_run(
    make: Callable[[list[Reply] | None], TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("bad shape")

    monkeypatch.setattr("menara_demo.runs.effects_for", boom)
    client = make([status_call(), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    state = wait_for(client, finished)
    assert state["status"] == "done" and not [e for e in state["events"] if e["type"] == "map"]


def test_effects_are_built_from_the_full_result_not_the_shortened_event_text(
    hub: FakeHub, make: Callable[[list[Reply] | None], TestClient]
) -> None:
    async def long_call(name: str, arguments: dict[str, Any]) -> str:
        return json.dumps({"synthetic": True, "data": {"status": "DOWN", "padding": "x" * 20000}})

    hub.call = long_call  # type: ignore[method-assign]
    client = make([status_call(), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    events = wait_for(client, finished)["events"]
    shown = next(e for e in events if e["type"] == "result")["text"]
    assert len(shown) < 20000 and any(e["type"] == "map" for e in events)
    assert len(shown) < 20000 and any(e["type"] == "map" for e in events)

def tilt_call(call_id: str) -> Reply:
    changes = [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": 4.0}]
    return Reply(None, [ToolCall(call_id, "ran_tilt_cells", {"changes": changes, "policy_token": "t"})])


def test_a_heal_event_follows_the_result_and_map_events(make: Callable[[list[Reply] | None], TestClient]) -> None:
    client = make([status_call(), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    events = wait_for(client, finished)["events"]
    kinds = [e["type"] for e in events]
    assert kinds.index("heal") == kinds.index("map") + 1
    heal = next(e for e in events if e["type"] == "heal")
    assert heal["step"] == 1 and heal["stage"] == "detect" and heal["attempt"] == 0 and "KKRI-0142" in heal["label"]


def test_the_second_tilt_is_attempt_2(make: Callable[[list[Reply] | None], TestClient]) -> None:
    client = make([tilt_call("a"), tilt_call("b"), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Fix", "clock": 20})
    heals = [e for e in wait_for(client, finished)["events"] if e["type"] == "heal"]
    assert [(h["stage"], h["attempt"]) for h in heals] == [("apply", 1), ("apply", 2)]


def test_a_human_decision_is_an_approve_event(make: Callable[[list[Reply] | None], TestClient]) -> None:
    client = make([drone_check(), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Drone", "clock": 20})
    wait_for(client, waiting)
    client.post("/api/agent/decision", json={"approve": True})
    heals = [(e["stage"], e["label"]) for e in wait_for(client, finished)["events"] if e["type"] == "heal"]
    assert ("approve", "Policy: a human approved") in heals
    assert ("approve", "Human approved") in heals


def test_a_failing_stage_builder_does_not_break_the_run(
    make: Callable[[list[Reply] | None], TestClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("bad shape")

    monkeypatch.setattr("menara_demo.heal.StageTracker.observe", boom)
    client = make([status_call(), Reply("done", [])])
    client.post("/api/agent/run", json={"mode": "live", "task": "Investigate", "clock": 20})
    state = wait_for(client, finished)
    assert state["status"] == "done" and not [e for e in state["events"] if e["type"] == "heal"]


def test_the_heal_state_route_answers_even_when_the_servers_have_nothing(make: Callable[[list[Reply] | None], TestClient]) -> None:
    reply = make([]).get("/api/heal/state")
    assert reply.status_code == 200
    body = reply.json()
    assert body["ok"] is True and body["failed_tower"] == "KKRI-0142" and body["threshold"] == 85.0
    assert body["watched"] == [] and body["changes"] == [] and body["incident"] is None and "clock_min" in body