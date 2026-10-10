from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from menara_agent.servers import McpHub, ServerSpec
from menara_agent.tools import HIDDEN_TOOLS, ToolInfo
from menara_core.testing import build_test_db
from menara_demo.app import create_app
from starlette.testclient import TestClient

SCHEMA = {"type": "object", "properties": {"enodeb_name": {"type": "string"}}, "required": ["enodeb_name"]}


class FakeHub:
    def __init__(self) -> None:
        self.tools = [ToolInfo("tower_get_status", "Status of a tower.", SCHEMA)] + [
            ToolInfo(name, "human only", SCHEMA) for name in sorted(HIDDEN_TOOLS)
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "tower_get_status" and arguments.get("enodeb_name") == "BOOM-0001":
            raise RuntimeError("Tower BOOM-0001 not found")
        if name == "tower_get_status":
            return json.dumps({"synthetic": True, "data": {"status": "DOWN"}})
        raise KeyError(name)


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return build_test_db(tmp_path)


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def client(hub: FakeHub, db_file: Path) -> Iterator[TestClient]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[FakeHub]:
        yield hub

    with TestClient(create_app(factory, db_file)) as test_client:
        yield test_client


def test_the_page_is_served_and_labelled_synthetic(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "SYNTHETIC" in page.text and "leaflet" in page.text.lower()


def test_tools_are_listed_without_the_human_only_ones(client: TestClient) -> None:
    tools = client.get("/api/tools").json()
    assert [t["name"] for t in tools] == ["tower_get_status"]
    assert tools[0]["description"] == "Status of a tower." and tools[0]["schema"] == SCHEMA


def test_a_call_returns_parsed_json_and_a_timing(client: TestClient, hub: FakeHub) -> None:
    reply = client.post("/api/call", json={"name": "tower_get_status", "arguments": {"enodeb_name": "KKRI-0142"}}).json()
    assert reply["ok"] is True and reply["result"]["data"]["status"] == "DOWN" and reply["ms"] >= 0
    assert hub.calls == [("tower_get_status", {"enodeb_name": "KKRI-0142"})]


def test_a_plain_text_result_comes_back_as_text(client: TestClient, hub: FakeHub, monkeypatch: pytest.MonkeyPatch) -> None:
    async def text_call(name: str, arguments: dict[str, Any]) -> str:
        return "not json at all"

    monkeypatch.setattr(hub, "call", text_call)
    reply = client.post("/api/call", json={"name": "tower_get_status", "arguments": {}}).json()
    assert reply["ok"] is True and reply["result"] == "not json at all"


def test_human_only_and_unknown_tools_are_refused(client: TestClient, hub: FakeHub) -> None:
    for name in sorted(HIDDEN_TOOLS):
        assert client.post("/api/call", json={"name": name, "arguments": {}}).status_code == 403
    assert client.post("/api/call", json={"name": "no_such_tool", "arguments": {}}).status_code == 404
    assert hub.calls == []


def test_a_tool_error_is_reported_not_raised(client: TestClient) -> None:
    response = client.post("/api/call", json={"name": "tower_get_status", "arguments": {"enodeb_name": "BOOM-0001"}})
    assert response.status_code == 200
    assert response.json() == {"ok": False, "error": "Tower BOOM-0001 not found"}


@pytest.mark.parametrize("body", [{}, {"name": 5}, {"name": "tower_get_status", "arguments": "x"}, [1, 2]])
def test_a_malformed_call_is_a_400(client: TestClient, body: Any) -> None:
    assert client.post("/api/call", json=body).status_code == 400
    assert client.post("/api/call", content="not json", headers={"content-type": "application/json"}).status_code == 400


def test_the_clock_can_be_read_and_set(client: TestClient) -> None:
    assert client.get("/api/clock").json()["t_min"] == 0
    assert client.post("/api/clock", json={"t_min": 12}).json()["t_min"] == 12
    now = client.get("/api/clock").json()
    assert now["t_min"] == 12 and now["as_of"].startswith("2026-11-14T07:12")


@pytest.mark.parametrize("value", [99999, -99999, "12", 1.5, None, True])
def test_a_bad_clock_value_is_a_400(client: TestClient, value: Any) -> None:
    assert client.post("/api/clock", json={"t_min": value}).status_code == 400
    assert client.get("/api/clock").json()["t_min"] == 0


def test_end_to_end_against_real_servers(db_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A circle search, an area list and a trail through the app, with real stdio MCP servers."""
    monkeypatch.setenv("MENARA_DB", str(db_file))
    specs = {
        "tower": ServerSpec(command=sys.executable, args=["-m", "tower_mcp"]),
        "user": ServerSpec(command=sys.executable, args=["-m", "user_mcp"]),
    }
    root = Path(__file__).resolve().parents[3]

    def factory() -> Any:
        return McpHub(specs, cwd=root)

    with TestClient(create_app(factory, db_file)) as real:
        assert {"tower_list_in_radius", "user_list_in_area", "user_get_trail"} <= {t["name"] for t in real.get("/api/tools").json()}
        towers = real.post("/api/call", json={"name": "tower_list_in_radius", "arguments": {"lat": 5.531, "lng": 102.197, "radius_km": 10}}).json()
        assert towers["ok"] and towers["result"]["data"]["towers"][0]["enodeb_name"] == "KKRI-0142"
        area = real.post("/api/call", json={"name": "user_list_in_area", "arguments": {"lat": 5.531, "lng": 102.197, "radius_km": 10, "limit": 5}}).json()
        digest = area["result"]["data"]["subscribers"][0]["msisdn_hash"]
        trail = real.post("/api/call", json={"name": "user_get_trail", "arguments": {"msisdn_hash": digest}}).json()
        assert trail["ok"] and trail["result"]["data"]["segments"]
        missing = real.post("/api/call", json={"name": "tower_get_status", "arguments": {"enodeb_name": "ZZZZ-9999"}}).json()
        assert missing["ok"] is False and "not found" in missing["error"].lower()