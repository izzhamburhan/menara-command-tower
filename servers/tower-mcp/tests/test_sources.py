"""The same behaviour must hold whichever TowerSource is behind the tools.

The HTTP source talks to a fake "Tower API v1" service. The fake is backed by the synthetic data, so any
difference in the results comes from the source layer, not from the data.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from menara_core.db import connect
from menara_core.errors import InvalidInputError, NotFoundError, SourceUnavailableError
from tower_mcp import tools
from tower_mcp.server import build_server, main
from tower_mcp.source import TowerSource
from tower_mcp.source_http import HttpSourceFactory, HttpTowerSource
from tower_mcp.source_sqlite import SqliteTowerSource

TOKEN = "secret"
BASE = "http://tower-api.test"
KK_BBOX = (5.40, 102.10, 5.70, 102.30)


# ---------- a fake Tower API v1, backed by the synthetic data ----------


def fake_api(db_file: Path, token: str = TOKEN) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {token}":
            return httpx.Response(401, json={"error": "unauthorised"})
        conn = connect(db_file)
        try:
            return _route(SqliteTowerSource(conn), request)
        finally:
            conn.close()

    return handler


def _route(src: SqliteTowerSource, request: httpx.Request) -> httpx.Response:
    path, q = request.url.path, request.url.params
    if path == "/towers":
        status = q.get("status")
        pins = src.list_towers(
            float(q["min_lat"]), float(q["min_lng"]), float(q["max_lat"]), float(q["max_lng"]), status, int(q["limit"])
        )
        return httpx.Response(200, json=[p.model_dump() for p in pins])
    if path == "/alarms":
        alarms = src.list_alarms(
            q.get("enodeb_name"), q.get("severity"), q.get("active_only", "true") == "true", int(q["limit"])
        )
        return httpx.Response(200, json=[a.model_dump() for a in alarms])
    match = re.fullmatch(r"/towers/([A-Z]{4}-\d{4})(?:/(status|neighbours|kpi))?", path)
    if not match:
        return httpx.Response(404)
    name, part = match.groups()
    if part is None:
        tower = src.get_tower(name)
        return httpx.Response(404) if tower is None else httpx.Response(200, json=tower.model_dump())
    if part == "status":
        state = src.get_status(name)
        return httpx.Response(404) if state is None else httpx.Response(200, json=state.model_dump())
    if part == "neighbours":
        return httpx.Response(200, json=[n.model_dump() for n in src.get_neighbours(name)])
    points = src.kpi_window(name, int(q["window_min"]))
    keys = ("at", "prb_util", "drop_rate", "throughput_mbps")
    return httpx.Response(200, json=[{k: getattr(p, k) for k in keys} for p in points])


def http_factory(handler: Callable[[httpx.Request], httpx.Response], token: str | None = TOKEN) -> HttpSourceFactory:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    client = httpx.Client(base_url=BASE, headers=headers, transport=httpx.MockTransport(handler))
    return HttpSourceFactory(BASE, token, client=client)


# ---------- fixtures ----------


@pytest.fixture(params=["sqlite", "http"])
def any_source(request: pytest.FixtureRequest, db_file: Path) -> Iterator[TowerSource]:
    if request.param == "sqlite":
        conn = connect(db_file)
        yield SqliteTowerSource(conn)
        conn.close()
    else:
        with http_factory(fake_api(db_file))() as source:
            yield source


# ---------- the same behaviour on both sources ----------


def test_status_is_the_same_on_both_sources(any_source: TowerSource) -> None:
    env = tools.get_status(any_source, "KKRI-0142")
    d = env.data
    assert d.status == "DOWN" and d.battery_pct == 14 and d.mains_ok is False
    assert d.active_alarm_count == 3 and "KKRI-0142-B1" in d.cells and d.site_id == "SITE-KKRI-0142"
    assert {n.enodeb_name: n.prb_util for n in d.neighbours}["KKRI-0143"] == 91.0
    assert d.latest_kpi is not None and d.latest_kpi.throughput_mbps == 0.0
    assert env.evidence[0].tool == "tower_get_status"


def test_bbox_is_the_same_on_both_sources(any_source: TowerSource) -> None:
    assert len(tools.list_in_bbox(any_source, *KK_BBOX).data.towers) == 12
    down = tools.list_in_bbox(any_source, *KK_BBOX, status="DOWN").data
    assert [t.enodeb_name for t in down.towers] == ["KKRI-0142"]
    truncated = tools.list_in_bbox(any_source, 0.0, 95.0, 8.0, 120.0, limit=5)
    assert truncated.data.returned == 5 and truncated.data.truncated is True and truncated.warnings


def test_kpi_is_the_same_on_both_sources(any_source: TowerSource) -> None:
    data = tools.get_kpi(any_source, "KKRI-0143", window_min=30).data
    assert data.summary.max_prb_util == 91.0 and data.summary.samples == len(data.points) > 0
    assert [p.at for p in data.points] == sorted(p.at for p in data.points)


def test_alarms_are_the_same_on_both_sources(any_source: TowerSource) -> None:
    alarms = tools.get_alarms(any_source, enodeb_name="KKRI-0142").data.alarms
    assert {a.code for a in alarms} == {"MAINS_FAIL", "LOW_BATTERY", "SITE_DOWN"}
    assert alarms[0].severity == "CRITICAL" and all(a.active for a in alarms)
    assert [a.code for a in tools.get_alarms(any_source, "KKRI-0143", severity="WARNING").data.alarms] == [
        "TRAFFIC_OVERLOAD"
    ]


def test_errors_are_the_same_on_both_sources(any_source: TowerSource) -> None:
    with pytest.raises(NotFoundError):
        tools.get_status(any_source, "ZZZZ-9999")
    with pytest.raises(InvalidInputError):
        tools.get_status(any_source, "kkri")
    with pytest.raises(NotFoundError):
        tools.get_alarms(any_source, enodeb_name="ZZZZ-9999")


# ---------- what differs: provenance ----------


def test_the_sqlite_source_is_synthetic_with_scenario_minutes(db_file: Path) -> None:
    conn = connect(db_file)
    source = SqliteTowerSource(conn)
    env = tools.get_kpi(source, "KKRI-0143")
    assert env.synthetic is True and source.as_of().startswith("2026-11-14T07:00")
    assert all(p.t_min is not None for p in env.data.points)
    conn.close()


def test_the_http_source_is_marked_not_synthetic(db_file: Path) -> None:
    with http_factory(fake_api(db_file))() as source:
        env = tools.get_kpi(source, "KKRI-0143")
        assert env.synthetic is False and not source.synthetic
        assert all(p.t_min is None for p in env.data.points)  # no scenario clock on a live source
        assert not env.as_of.startswith("2026-11-14T07:00")  # it is the time of the call, not the scenario


# ---------- the upstream misbehaving ----------


def _factory_returning(response: httpx.Response | Exception) -> HttpSourceFactory:
    def handler(_: httpx.Request) -> httpx.Response:
        if isinstance(response, Exception):
            raise response
        return response

    return http_factory(handler)


def test_an_unknown_tower_is_not_found_not_an_error() -> None:
    with _factory_returning(httpx.Response(404))() as source, pytest.raises(NotFoundError):
        tools.get_status(source, "KKRI-0142")


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500, text="boom"),
        httpx.Response(503),
        httpx.Response(401),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"unexpected": "shape"}),
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
    ],
)
def test_upstream_failures_become_one_clear_error(response: httpx.Response | Exception) -> None:
    with _factory_returning(response)() as source, pytest.raises(SourceUnavailableError, match="Tower API"):
        tools.list_in_bbox(source, *KK_BBOX)


def test_a_wrong_token_is_rejected_by_the_upstream(db_file: Path) -> None:
    with http_factory(fake_api(db_file), token="wrong")() as source, pytest.raises(SourceUnavailableError, match="401"):
        tools.get_status(source, "KKRI-0142")


def test_the_source_never_returns_partial_garbage(db_file: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/kpi"):
            return httpx.Response(200, json=[{"at": "2026-01-01T00:00:00+08:00", "prb_util": "high"}])
        return fake_api(db_file)(request)

    with http_factory(handler)() as source, pytest.raises(SourceUnavailableError, match="does not match the contract"):
        tools.get_kpi(source, "KKRI-0143")
    assert isinstance(source, HttpTowerSource)


# ---------- through the server ----------


def test_the_server_runs_on_the_http_source_and_says_so(db_file: Path) -> None:
    server = build_server(http_factory(fake_api(db_file)))
    assert "live tower API" in (server.instructions or "")
    result = asyncio.run(server.call_tool("tower_get_status", {"enodeb_name": "KKRI-0142"}))
    payload: dict[str, Any] = result[1] if isinstance(result, tuple) else result
    assert payload["synthetic"] is False and payload["data"]["status"] == "DOWN"


def test_the_sqlite_server_still_says_synthetic(db_file: Path) -> None:
    from tower_mcp.source_sqlite import SqliteSourceFactory

    assert "SYNTHETIC" in (build_server(SqliteSourceFactory(db_file)).instructions or "")


def test_the_http_source_needs_an_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MENARA_TOWER_API_URL", raising=False)
    with pytest.raises(SystemExit):
        main(["--source", "http"])