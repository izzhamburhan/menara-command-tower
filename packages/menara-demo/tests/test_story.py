"""Trail narration: the backend gathers the facts, the model only writes them up. A fake hub and a fake model."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
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
    {"critical_site_id": "CS-3", "name": "Tawau Mall 3 (synthetic)", "kind": "MALL", "lat": 4.5, "lng": 118.1, "serving_enodeb": "AAAA-0009"},
]


LONG = "aaaaaaaaaaaaaaaa"
START = datetime.fromisoformat("2026-10-17T07:12:00+08:00")  # four weeks before the clock at minute 12 (a Saturday)


def long_trail() -> dict[str, Any]:
    """Home all month, with a three-hour trip to the mall tower on a Saturday of each of the four weekends."""
    stays: list[tuple[str, datetime, int]] = [("AAAA-0001", START, 600)]
    for weekend in range(4):
        trip = START.replace(hour=11, minute=0) + timedelta(days=7 * weekend)
        stays += [("AAAA-0009", trip, 180), ("AAAA-0001", trip + timedelta(minutes=180), 600)]
    segments = []
    for index, (tower, arrival, minutes) in enumerate(stays):
        last = index == len(stays) - 1
        segments.append(
            {"serving_cell": f"{tower}-B1", "enodeb_name": tower, "cell_lat": 4.5 if tower == "AAAA-0009" else 4.2, "cell_lng": 118.1 if tower == "AAAA-0009" else 117.8, "arrived_at": arrival.isoformat(),
             "left_at": None if last else stays[index + 1][1].isoformat(), "duration_min": minutes, "current": last}
        )
    return {"synthetic": True, "data": {"msisdn_hash": LONG, "window_min": 40320, "window_start": START.isoformat(), "moves": len(segments) - 1, "segments": segments}}


class FakeHub:
    def __init__(self) -> None:
        self.tools = [ToolInfo("user_get_trail", "d", {"type": "object"}), ToolInfo("sites_list_in_bbox", "d", {"type": "object"})]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "user_get_trail":
            if arguments["msisdn_hash"] == "ffffffffffffffff":
                raise RuntimeError(f"Subscriber {arguments['msisdn_hash']} not found")
            return json.dumps(long_trail() if arguments["msisdn_hash"] == LONG else TRAIL)
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


def prompt_text(llm: RecordingLLM) -> str:
    return chr(10).join(str(m["content"]) for m in llm.seen)


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
    assert reply.status_code == 502 and "upstream timeout" in reply.json()["error"]

def test_the_story_asks_for_four_weeks_and_returns_routines(client: TestClient, hub: FakeHub) -> None:
    reply = client.post("/api/trail/story", json={"msisdn_hash": DIGEST}).json()
    assert ("user_get_trail", {"msisdn_hash": DIGEST, "window_min": 40320}) in hub.calls
    assert reply["routines"] == reply["facts"]["routines"]
    assert [r["kind"] for r in reply["routines"]] == ["home"] and "Tawau School 7 (synthetic)" in reply["routines"][0]["sentence"]


def test_a_weekend_mall_habit_is_counted_by_the_backend(client: TestClient) -> None:
    reply = client.get("/api/trail/routines", params={"msisdn_hash": LONG}).json()
    weekend = [r for r in reply["routines"] if r["kind"] == "weekend"]
    assert len(weekend) == 1
    assert weekend[0]["sentence"] == "Weekends: near Tawau Mall 3 (synthetic) on 4 of 4 weekends, usually about 3 h from about 11:00"
    mall = next(t for t in reply["facts"]["towers"] if t["tower"] == "AAAA-0009")
    assert mall["nearby_sites"][0]["kind"] == "MALL" and {"lat", "lng"} <= set(mall["nearby_sites"][0])
    assert mall["weekend_weekends"] == 4 and mall["weekday_days"] == 0


def test_routines_work_without_a_model_key(hub: FakeHub, tmp_path: Path) -> None:
    with client_for(hub, None, tmp_path) as client:
        reply = client.get("/api/trail/routines", params={"msisdn_hash": LONG})
    assert reply.status_code == 200 and reply.json()["ok"] is True and "story" not in reply.json()


def test_routines_errors_are_mapped(client: TestClient) -> None:
    assert client.get("/api/trail/routines", params={"msisdn_hash": "nope"}).status_code == 400
    assert client.get("/api/trail/routines", params={"msisdn_hash": DIGEST, "window_min": "x"}).status_code == 400
    assert client.get("/api/trail/routines", params={"msisdn_hash": DIGEST, "window_min": "40321"}).status_code == 400
    assert client.get("/api/trail/routines", params={"msisdn_hash": "ffffffffffffffff"}).status_code == 404


def test_the_prompt_sends_routines_and_recent_stops_not_four_weeks_of_segments(client: TestClient, llm: RecordingLLM) -> None:
    client.post("/api/trail/story", json={"msisdn_hash": LONG})
    text = prompt_text(llm)
    assert "Weekends: near Tawau Mall 3 (synthetic) on 4 of 4 weekends" in text
    assert '"segments"' not in text and "recent_segments" in text
    for rule in ("never state a frequency that is not in the facts", "routines", "synthetic subscriber"):
        assert rule in text


def test_the_story_window_can_reach_four_weeks(client: TestClient) -> None:
    assert client.post("/api/trail/story", json={"msisdn_hash": DIGEST, "window_min": 40320}).status_code == 200
    assert client.post("/api/trail/story", json={"msisdn_hash": DIGEST, "window_min": 40321}).status_code == 400