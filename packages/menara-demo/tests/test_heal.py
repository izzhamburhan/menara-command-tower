"""The self-heal view: which stage of the loop a tool call is, and the loop's state (KPI series, changes, incident)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from menara_demo.heal import (
    FLOOD_ANCHOR,
    STAGES,
    THRESHOLD_PRB,
    StageTracker,
    heal_state,
    stage_for,
)


def wrap(data: dict[str, Any]) -> str:
    return json.dumps({"synthetic": True, "data": data})


@pytest.mark.parametrize(
    ("name", "arguments", "stage"),
    [
        ("ticket_get_ticket", {"ticket_id": "TK-1"}, "detect"),
        ("ticket_cluster_by_location", {}, "detect"),
        ("tower_get_status", {"enodeb_name": "KKRI-0142"}, "detect"),
        ("tower_get_alarms", {}, "detect"),
        ("grid_get_tower_power", {}, "diagnose"),
        ("grid_get_feeder_status", {}, "diagnose"),
        ("flood_get_gauge", {}, "diagnose"),
        ("flood_check_point", {}, "diagnose"),
        ("weather_get_rainfall", {}, "diagnose"),
        ("ontology_blast_radius", {}, "diagnose"),
        ("ontology_create_incident", {}, "diagnose"),
        ("twin_simulate_tilt", {}, "simulate"),
        ("twin_simulate_failure", {}, "simulate"),
        ("policy_check_action", {}, "approve"),
        ("ran_tilt_cells", {}, "apply"),
        ("drone_dispatch", {}, "apply"),
        ("tower_get_kpi", {}, "verify"),
        ("ran_revert_change", {}, "rollback"),
        ("ontology_update_incident", {"status": "RESOLVED"}, "recover"),
    ],
)
def test_each_tool_maps_to_its_stage(name: str, arguments: dict[str, Any], stage: str) -> None:
    assert stage_for(name, arguments) == stage and stage in STAGES


@pytest.mark.parametrize(
    ("name", "arguments"),
    [("ontology_update_incident", {"status": "MITIGATING"}), ("sites_list_in_bbox", {}), ("usage_top_apps_in_area", {}), ("nonsense", {})],
)
def test_other_tools_have_no_stage(name: str, arguments: dict[str, Any]) -> None:
    assert stage_for(name, arguments) is None


def test_the_eight_stages_are_in_loop_order() -> None:
    assert STAGES == ("detect", "diagnose", "simulate", "approve", "apply", "verify", "rollback", "recover")


def test_the_tracker_counts_tilt_attempts_and_labels_the_stage() -> None:
    tracker = StageTracker()
    tilt = {"changes": [{"enodeb_name": "KKRI-0143", "tilt_delta_deg": 4.0}, {"enodeb_name": "KKRI-0144", "tilt_delta_deg": 4.0}]}
    first = tracker.observe("ran_tilt_cells", tilt, wrap({"change_id": "CHG-0001"}))
    assert first and first["stage"] == "apply" and first["attempt"] == 1 and "KKRI-0143" in first["label"]
    verify = tracker.observe("tower_get_kpi", {"enodeb_name": "KKRI-0143"}, wrap({"summary": {"max_prb_util": 88.2}}))
    assert verify and verify["stage"] == "verify" and verify["attempt"] == 1 and "88.2" in verify["label"]
    undo = tracker.observe("ran_revert_change", {"change_id": "CHG-0001"}, wrap({"change_id": "CHG-0001"}))
    assert undo and undo["stage"] == "rollback" and undo["attempt"] == 1 and "CHG-0001" in undo["label"]
    second = tracker.observe("ran_tilt_cells", tilt, wrap({"change_id": "CHG-0002"}))
    assert second and second["attempt"] == 2
    drone = tracker.observe("drone_dispatch", {"enodeb_name": "KKRI-0142"}, wrap({"mission_id": "MIS-0001"}))
    assert drone and drone["stage"] == "apply" and drone["attempt"] == 0  # a drone is not a tilt attempt


def test_a_failed_call_or_an_unmapped_tool_gives_nothing() -> None:
    tracker = StageTracker()
    assert tracker.observe("sites_list_in_bbox", {}, wrap({})) is None
    assert tracker.observe("ran_tilt_cells", {}, "Error: policy token missing", ok=False) is None
    assert tracker.observe("ran_tilt_cells", {}, wrap({"change_id": "CHG-0001"}))["attempt"] == 1  # type: ignore[index]


class FakeHub:
    """Canned answers shaped like the real servers'. `series` maps a tower to its PRB over scenario minutes."""

    def __init__(self, series: dict[str, list[float]], changes: list[dict[str, Any]] | None = None, incidents: list[dict[str, Any]] | None = None) -> None:
        self.series = series
        self.changes = changes or []
        self.incidents = incidents or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        self.calls.append((name, arguments))
        if name == "tower_get_status":
            tower = arguments["enodeb_name"]
            return wrap({"enodeb_name": tower, "status": "DOWN", "neighbours": [{"enodeb_name": n, "distance_km": 3.0, "status": "UP", "prb_util": v[-1]} for n, v in self.series.items()]})
        if name == "tower_get_kpi":
            values = self.series[arguments["enodeb_name"]]
            window = arguments["window_min"]
            now = (len(values) - 1) * 5
            points = [{"t_min": t * 5, "at": "x", "prb_util": v, "drop_rate": 1.0, "throughput_mbps": 20.0} for t, v in enumerate(values) if t * 5 >= now - window]
            return wrap({"enodeb_name": arguments["enodeb_name"], "window_min": window, "points": points, "summary": {"max_prb_util": max(values)}})
        if name == "ran_list_changes":
            return wrap({"changes": self.changes, "returned": len(self.changes)})
        if name == "ontology_list_incidents":
            return wrap({"incidents": self.incidents, "returned": len(self.incidents)})
        raise KeyError(name)


START = "2026-11-14T07:00:00+08:00"


def change(change_id: str, status: str, applied: str, reverted: str | None, towers: list[str]) -> dict[str, Any]:
    return {"change_id": change_id, "action": "ran_tilt_cells", "status": status, "applied_at": applied, "reverted_at": reverted, "towers": towers, "items": []}


def test_before_any_run_there_is_a_series_no_changes_and_no_incident() -> None:
    hub = FakeHub({"KKRI-0143": [91.0] * 6, "KKRI-0144": [91.0] * 6, "KKRI-0150": [40.0] * 6})
    state = asyncio.run(heal_state(hub, clock_min=25, as_of="2026-11-14T07:25:00+08:00"))
    assert state["failed_tower"] == FLOOD_ANCHOR and state["incident"] is None and state["changes"] == []
    assert state["threshold"] == THRESHOLD_PRB == 85.0
    assert state["watched"] == ["KKRI-0143", "KKRI-0144"]  # KKRI-0150 never got near the threshold
    assert [p["t_min"] for p in state["series"]["KKRI-0143"]] == [0, 5, 10, 15, 20, 25]
    assert state["clock_min"] == 25


def test_the_incident_tower_is_the_failed_tower_and_the_latest_incident_wins() -> None:
    hub = FakeHub(
        {"KKRI-0143": [91.0] * 3},
        incidents=[
            {"incident_id": "INC-0001", "enodeb_name": "AAAA-0001", "status": "RESOLVED", "created_at": "2026-11-14T07:01:00+08:00"},
            {"incident_id": "INC-0002", "enodeb_name": "KKRI-0142", "status": "OPEN", "created_at": "2026-11-14T07:09:00+08:00"},
        ],
    )
    state = asyncio.run(heal_state(hub, clock_min=10, as_of="2026-11-14T07:10:00+08:00"))
    assert state["failed_tower"] == "KKRI-0142" and state["incident"] == {"incident_id": "INC-0002", "status": "OPEN"}
    assert ("tower_get_status", {"enodeb_name": "KKRI-0142"}) in hub.calls


def test_every_changed_tower_is_watched_and_changes_carry_minutes() -> None:
    hub = FakeHub(
        {"KKRI-0143": [91.0, 91.0, 88.2, 88.2, 63.0], "KKRI-0144": [91.0, 91.0, 63.0, 63.0, 63.0], "KKRI-0150": [30.0] * 5},
        changes=[
            change("CHG-0001", "REVERTED", "2026-11-14T07:10:00+08:00", "2026-11-14T07:15:00+08:00", ["KKRI-0143", "KKRI-0144"]),
            change("CHG-0002", "ACTIVE", "2026-11-14T07:16:00+08:00", None, ["KKRI-0150"]),
        ],
    )
    state = asyncio.run(heal_state(hub, clock_min=20, as_of="2026-11-14T07:20:00+08:00"))
    assert state["watched"] == ["KKRI-0143", "KKRI-0144", "KKRI-0150"]
    assert [(c["change_id"], c["applied_min"], c["reverted_min"], c["status"]) for c in state["changes"]] == [
        ("CHG-0001", 10, 15, "REVERTED"), ("CHG-0002", 16, None, "ACTIVE"),
    ]
    assert state["changes"][0]["towers"] == ["KKRI-0143", "KKRI-0144"]


def test_the_window_is_capped_at_1440_minutes() -> None:
    hub = FakeHub({"KKRI-0143": [91.0] * 3})
    asyncio.run(heal_state(hub, clock_min=5000, as_of="2026-11-14T07:00:00+08:00"))
    windows = [a["window_min"] for n, a in hub.calls if n == "tower_get_kpi"]
    assert windows and max(windows) == 1440
    hub2 = FakeHub({"KKRI-0143": [91.0] * 3})
    asyncio.run(heal_state(hub2, clock_min=0, as_of=START))
    assert min(a["window_min"] for n, a in hub2.calls if n == "tower_get_kpi") == 240


def test_a_long_series_is_thinned_to_at_most_200_points() -> None:
    hub = FakeHub({"KKRI-0143": [91.0] * 600})
    state = asyncio.run(heal_state(hub, clock_min=1440, as_of="2026-11-15T07:00:00+08:00"))
    assert 2 <= len(state["series"]["KKRI-0143"]) <= 200
    assert state["series"]["KKRI-0143"][-1]["t_min"] == 2995  # the newest point is kept

def test_changes_and_incidents_after_the_clock_are_not_shown_yet() -> None:
    hub = FakeHub(
        {"KKRI-0143": [91.0] * 4},
        changes=[change("CHG-0001", "ACTIVE", "2026-11-14T07:10:00+08:00", None, ["KKRI-0143"])],
        incidents=[{"incident_id": "INC-0001", "enodeb_name": "AAAA-0001", "status": "OPEN", "created_at": "2026-11-14T07:09:00+08:00"}],
    )
    early = asyncio.run(heal_state(hub, clock_min=5, as_of="2026-11-14T07:05:00+08:00"))  # the clock was moved back
    assert early["changes"] == [] and early["incident"] is None and early["failed_tower"] == FLOOD_ANCHOR
    later = asyncio.run(heal_state(hub, clock_min=15, as_of="2026-11-14T07:15:00+08:00"))
    assert [c["change_id"] for c in later["changes"]] == ["CHG-0001"] and later["incident"]["incident_id"] == "INC-0001"
