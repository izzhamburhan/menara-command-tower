"""Replay: the whole incident flow driven by a fixed script through real stdio MCP servers on a scratch database."""

from __future__ import annotations

import json
import re
import sys
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from menara_agent.servers import McpHub, load_config
from menara_core import settings
from menara_core.testing import build_test_db
from menara_demo.app import create_app
from menara_demo.app_types import Hub
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[3]
NEEDED = {"ticket", "tower", "grid", "flood", "ontology", "twin", "policy", "drone", "ran"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_file = build_test_db(tmp_path)
    monkeypatch.setenv("MENARA_DB", str(db_file))
    specs = {n: s for n, s in load_config(REPO_ROOT / ".mcp.json").items() if n in NEEDED}
    specs = {n: type(s)(sys.executable, ["-m", s.args[-1]], dict(s.env)) for n, s in specs.items()}

    @asynccontextmanager
    async def factory() -> AsyncIterator[Hub]:
        async with McpHub(specs, cwd=REPO_ROOT) as hub:
            yield hub

    with TestClient(create_app(factory, db_file, approver_key=settings.approver_key())) as test_client:
        yield test_client


def play(client: TestClient, decisions: list[bool], timeout: float = 120.0) -> dict[str, Any]:
    """Start a replay and answer each approval prompt from `decisions`, in order."""
    assert client.post("/api/agent/run", json={"mode": "replay", "clock": 12}).status_code == 200
    answers = iter(decisions)
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/agent/events").json()
        if state["status"] != "running":
            return state  # type: ignore[no-any-return]
        if state["pending_approval"] is not None:
            client.post("/api/agent/decision", json={"approve": next(answers)})
        time.sleep(0.05)
    raise AssertionError("replay timed out")


def results(state: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [e for e in state["events"] if e["type"] == "result" and e["name"] == name]


def test_replay_needs_no_model_and_walks_the_whole_story(client: TestClient) -> None:
    assert client.get("/api/agent/status").json()["live_available"] is False
    state = play(client, [True, True, True])
    assert state["status"] == "done" and state["events"][-1]["type"] == "final"
    names = [e["name"] for e in state["events"] if e["type"] == "call"]
    for expected in ("ticket_get_ticket", "ontology_create_incident", "twin_simulate_tilt", "drone_dispatch", "drone_get_mission"):
        assert expected in names
    assert names.count("ran_tilt_cells") == 2 and names.count("ran_revert_change") == 2
    assert sum(1 for e in state["events"] if e["type"] == "approval") == 3  # drone, first tilt, second tilt
    assert all(r["ok"] for r in results(state, "ran_tilt_cells") + results(state, "ran_revert_change"))
    assert "COMPLETE" in results(state, "drone_get_mission")[0]["text"]
    first_kpi = results(state, "tower_get_kpi")
    assert '"prb_util": 91.0' in first_kpi[0]["text"] or "88.2" in first_kpi[0]["text"]
    assert '"status": "UP"' in results(state, "tower_get_status")[-1]["text"]  # power is back at the end
    assert "RESOLVED" in results(state, "ontology_update_incident")[-1]["text"]
    assert settings.approver_key() not in json.dumps(state)


def test_replay_stops_cleanly_when_the_human_rejects_the_drone(client: TestClient) -> None:
    state = play(client, [False])
    assert state["status"] == "done"
    names = [e["name"] for e in state["events"] if e["type"] == "call"]
    assert "drone_dispatch" not in names and "ran_tilt_cells" not in names
    assert "reject" in state["events"][-1]["text"].lower()
    assert "reject" in state["events"][-1]["text"].lower()

def test_replay_draws_the_incident_on_the_map(client: TestClient) -> None:
    state = play(client, [True, True, True])
    maps = [e for e in state["events"] if e["type"] == "map"]
    by_step = {e["step"]: e["effects"] for e in maps}
    calls = {e["step"]: e["name"] for e in state["events"] if e["type"] == "call"}
    kinds = {calls[step] for step in by_step}
    assert {"tower_get_status", "ontology_blast_radius", "flood_get_gauge", "drone_get_mission", "ran_tilt_cells"} <= kinds
    blast = next(effects for step, effects in by_step.items() if calls[step] == "ontology_blast_radius")
    assert any(e["kind"] == "ring" for e in blast) and any(e["kind"] == "pin" for e in blast)
    down = next(effects for step, effects in by_step.items() if calls[step] == "tower_get_status")
    assert down[0]["tone"] == "bad"
    assert all(0 < e["lat"] < 10 and 95 < e["lng"] < 120 for effects in by_step.values() for e in effects)  # Malaysia
    assert all(0 < e["lat"] < 10 and 95 < e["lng"] < 120 for effects in by_step.values() for e in effects)  # Malaysia

def ids_in(state: dict[str, Any]) -> dict[str, str]:
    text = json.dumps(state["events"])
    found: dict[str, str] = {}
    for prefix in ("INC", "CHG", "APR", "MIS", "SIM"):
        match = re.search(prefix + r"-\d{4}", text)
        if match:
            found[prefix] = match.group(0)
    return found


def test_replay_twice_with_a_reset_between_gives_the_same_ids(client: TestClient) -> None:
    first = play(client, [True, True, True])
    first_ids = ids_in(first)
    assert {"INC", "CHG", "APR", "MIS", "SIM"} <= set(first_ids)
    reset = client.post("/api/reset")
    assert reset.status_code == 200 and reset.json()["deleted"]["incident"] >= 1 and reset.json()["clock"]["t_min"] == 0
    assert client.get("/api/agent/events").json()["events"] == []
    second = play(client, [True, True, True])
    assert second["status"] == "done" and ids_in(second) == first_ids

def test_replay_emits_the_eight_stages_in_order(client: TestClient) -> None:
    state = play(client, [True, True, True])
    heals = [e for e in state["events"] if e["type"] == "heal"]
    stages = [h["stage"] for h in heals]
    first = [stages.index(s) for s in ("detect", "diagnose", "simulate", "approve", "apply", "verify", "rollback", "recover")]
    assert first == sorted(first)
    second_tilt = next(i for i, h in enumerate(heals) if h["stage"] == "apply" and h["attempt"] == 2)
    assert stages.index("rollback") < second_tilt and stages[-1] in {"recover", "verify", "approve", "rollback"}
    assert [h["attempt"] for h in heals if h["stage"] == "apply" and h["attempt"]] == [1, 2]
    assert any(h["label"] == "Human approved" for h in heals)


def test_heal_state_after_the_replay_shows_the_failed_then_the_good_tilt(client: TestClient) -> None:
    before = client.get("/api/heal/state").json()
    assert before["ok"] is True and before["changes"] == [] and before["incident"] is None
    play(client, [True, True, True])
    state = client.get("/api/heal/state").json()
    assert state["failed_tower"] == "KKRI-0142" and state["incident"]["status"] == "RESOLVED"
    assert {"KKRI-0143", "KKRI-0144"} <= set(state["watched"])
    first, second = state["changes"][0], state["changes"][1]
    assert first["status"] == "REVERTED" and first["reverted_min"] is not None
    series = state["series"]["KKRI-0143"]
    before_fix = [p["prb"] for p in series if 0 <= p["t_min"] < first["applied_min"]]  # from T0: the overload began at -5
    after_first = [p["prb"] for p in series if first["applied_min"] <= p["t_min"] < first["reverted_min"]]
    during_second = [p["prb"] for p in series if second["applied_min"] <= p["t_min"] < (second["reverted_min"] or 10**6)]
    assert before_fix and min(before_fix) >= state["threshold"]
    assert after_first and min(after_first) >= state["threshold"]  # the first tilt did not help enough
    assert during_second and max(during_second) < state["threshold"]  # the second one did
