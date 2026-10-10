"""Trail narration: the backend gathers the facts, the model only writes them up. A fake hub and a fake model."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from menara_agent.loop import Reply
from menara_agent.tools import ToolInfo
from menara_core.testing import build_test_db
from menara_demo.app import create_app
from starlette.testclient import TestClient

DIGEST = "0123456789abcdef"
TRAIL = {
    "synthetic": True,
    "data": {
        "msisdn_hash": DIGEST,
        "window_min": 1440,
        "window_start": "2026-11-13T09:30:00+08:00",
        "moves": 2,
        "segments": [
            {"serving_cell": "AAAA-0001-B1", "enodeb_name": "AAAA-0001", "cell_lat": 4.200, "cell_lng": 117.800,
             "arrived_at": "2026-11-13T18:00:00+08:00", "left_at": "2026-11-14T07:30:00+08:00", "duration_min": 810, "current": False},
            {"serving_cell": "AAAA-0002-B1", "enodeb_name": "AAAA-0002", "cell_lat": 4.230, "cell_lng": 117.830,
             "arrived_at": "2026-11-14T07:30:00+08:00", "left_at": "2026-11-14T08:00:00+08:00", "duration_min": 30, "current": False},
            {"serving_cell": "AAAA-0003-B1", "enodeb_name": "AAAA-0003", "cell_lat": 4.300, "cell_lng": 117.900,
             "arrived_at": "2026-11-14T08:00:00+08:00", "left_at": None, "duration_min": 90, "current": True},
        ],
    },
}
SITES = [  # near AAAA-0001 (0.4 km away) and far from the others
    {"critical_site_id": "CS-1", "name": "Tawau School 7 (synthetic)", "kind": "SCHOOL", "lat": 4.2036, "lng": 117.800, "serving_enodeb": "AAAA-0001"},
    {"critical_site_id": "CS-2", "name": "Tawau Hospital 2 (synthetic)", "kind": "HOSPITAL", "lat": 4.2300, "lng": 117.8300, "serving_enodeb": "AAAA-0002"},
]


class FakeHub:
    def __init__(self) -> None:
        self.tools = [ToolInfo("user_get_trail", "d", {"type": "object"}), ToolInfo("sites_list_in_bbox", "d", {"type": "object"})]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "user_get_trail":
            if arguments["msisdn_hash"] == "ffffffffffffffff":
                raise RuntimeError(f"Subscriber {arguments['msisdn_hash']} not found")
            return json.dumps(TRAIL)
        if name == "sites_list_in_bbox":
            inside = [
                s for s in SITES
                if arguments["min_lat"] <= s["lat"] <= arguments["max_lat"] and arguments["min_lng"] <= s["lng"] <= arguments["max_lng"]
            ]
            return json.dumps({"synthetic": True, "data": {"sites": inside, "returned": len(inside), "truncated": False}})
        raise KeyError(name)


class RecordingLLM:
    def __init__(self, text: str = "Overnight near AAAA-0001, then near a school.") -> None:
        self.text = text
        self.seen: list[dict[str, Any]] = []
        self.tools_given: list[Any] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        self.seen = messages
        self.tools_given = tools
        return Reply(self.text, [])


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


def client_for(hub: FakeHub, llm: RecordingLLM | None, tmp_path: Path) -> TestClient:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeHub]:
        yield hub

    return TestClient(create_app(factory, build_test_db(tmp_path), llm=llm, approver_key="k", model_name="fake"))


@pytest.fixture
def llm() -> RecordingLLM:
    return RecordingLLM()


@pytest.fixture
def client(hub: FakeHub, llm: RecordingLLM, tmp_path: Path) -> Iterator[TestClient]:
    with client_for(hub, llm, tmp_path) as test_client:
        yield test_client


def test_the_story_comes_with_the_facts_it_was_built_from(client: TestClient, llm: RecordingLLM) -> None:
    reply = client.post("/api/trail/story", json={"msisdn_hash": DIGEST}).json()
    assert reply["ok"] is True and reply["story"] == "Overnight near AAAA-0001, then near a school." and reply["model"] == "fake"
    segments = reply["facts"]["segments"]
    assert [s["tower"] for s in segments] == ["AAAA-0001", "AAAA-0002", "AAAA-0003"]
    assert segments[0]["minutes"] == 810 and segments[0]["part_of_day"] == "evening" and segments[0]["hour"] == 18
    assert segments[2]["current"] is True


def test_nearby_sites_come_from_sites_mcp_with_distances_and_a_tower_with_none_says_so(client: TestClient, hub: FakeHub) -> None:
    facts = client.post("/api/trail/story", json={"msisdn_hash": DIGEST}).json()["facts"]
    near = {t["tower"]: t["nearby_sites"] for t in facts["towers"]}
    assert [(s["name"], s["kind"]) for s in near["AAAA-0001"]] == [("Tawau School 7 (synthetic)", "SCHOOL")]
    assert 0.3 < near["AAAA-0001"][0]["distance_km"] < 0.6
    assert near["AAAA-0002"][0]["kind"] == "HOSPITAL" and near["AAAA-0003"] == []
    asked = [c for c in hub.calls if c[0] == "sites_list_in_bbox"]
    assert len(asked) == 3  # one lookup per distinct tower


def test_the_prompt_holds_the_facts_and_the_honesty_rules_and_gives_the_model_no_tools(client: TestClient, llm: RecordingLLM) -> None:
    client.post("/api/trail/story", json={"msisdn_hash": DIGEST})
    text = "\n".join(str(m["content"]) for m in llm.seen)
    for needle in ("AAAA-0001", "Tawau School 7 (synthetic)", "only the places listed", "near", "probably home", "synthetic"):
        assert needle in text
    assert "no known site" in text.lower()
    assert llm.tools_given == []


def test_errors_are_mapped(client: TestClient, hub: FakeHub, tmp_path: Path) -> None:
    assert client.post("/api/trail/story", json={"msisdn_hash": "not-a-hash"}).status_code == 400
    assert client.post("/api/trail/story", json={"msisdn_hash": DIGEST, "window_min": 1}).status_code == 400
    assert client.post("/api/trail/story", json={"msisdn_hash": "ffffffffffffffff"}).status_code == 404
    assert client.post("/api/trail/story", content=b"nope").status_code == 400


def test_without_a_model_key_it_is_503_and_explains(hub: FakeHub, tmp_path: Path) -> None:
    with client_for(hub, None, tmp_path) as client:
        reply = client.post("/api/trail/story", json={"msisdn_hash": DIGEST})
    assert reply.status_code == 503 and "DEEPSEEK_API_KEY" in reply.json()["error"]


def test_a_model_failure_is_reported_not_raised(hub: FakeHub, tmp_path: Path) -> None:
    class Broken:
        async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
            raise RuntimeError("upstream timeout")

    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeHub]:
        yield hub

    app = create_app(factory, build_test_db(tmp_path), llm=Broken(), approver_key="k", model_name="fake")
    with TestClient(app) as client:
        reply = client.post("/api/trail/story", json={"msisdn_hash": DIGEST})
    assert reply.status_code == 502 and "upstream timeout" in reply.json()["error"]