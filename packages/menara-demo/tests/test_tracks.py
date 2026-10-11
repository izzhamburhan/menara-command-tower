"""The Tracks tab backend: which hackathon track a tool belongs to, the track events, and the six cards."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from menara_core import clock
from menara_core.db import connect
from menara_core.testing import build_test_db
from menara_demo import tracks
from menara_demo.tracks import TRACKS, TrackTracker, track_for, tracks_state

NEW_TOOLS = {
    "energy_get_tower": 5, "energy_find_savings": 5, "energy_apply_sleep": 5,
    "care_get_impact": 3, "care_draft_notice": 3, "care_send_notice": 3, "care_list_notices": 3,
    "enterprise_get_revenue_at_risk": 6, "enterprise_list_accounts": 6, "enterprise_issue_credit": 6,
    "exposure_list_profiles": 6, "exposure_quote": 6, "exposure_book": 6,
    "field_find_crew": 2, "field_dispatch": 2, "field_list_jobs": 2,
    "events_list_upcoming": 4, "events_forecast_load": 4, "events_capacity_plan": 4,
    "sensors_list_in_area": 5, "sensors_get_readings": 5, "sensors_get_alerts": 5,
    "scam_get_hotspots": 3, "scam_get_pattern": 3, "scam_estimate_protection": 3,
}


def test_every_new_tool_belongs_to_one_track_and_unknown_tools_have_none() -> None:
    assert set(TRACKS) == {1, 2, 3, 4, 5, 6}
    for name, number in NEW_TOOLS.items():
        assert track_for(name) == number, name
    assert track_for("tower_get_status") == 4 and track_for("ran_tilt_cells") == 4
    assert track_for("ontology_create_incident") == 1 and track_for("drone_dispatch") == 1
    assert track_for("demo_advance_clock") is None and track_for("nothing_like_it") is None


def test_policy_and_draft_calls_get_readable_labels() -> None:
    tracker = TrackTracker()
    asked = tracker.observe("policy_check_action", {"action": "comms_send_notice"}, json.dumps({"data": {"decision": "ask"}}))
    assert asked is not None and asked["track"] == 1 and asked["label"] == "Policy for comms_send_notice: ask"
    draft = tracker.observe("care_draft_notice", {}, json.dumps({"data": {"language": "ms", "recipients_est": 980, "cost_rm": 78.4}}))
    assert draft is not None and "980" in draft["label"] and "ms" in draft["label"]


def test_the_tracker_words_a_track_event_from_the_result() -> None:
    tracker = TrackTracker()
    sent = json.dumps({"data": {"notice_id": "NTC-0001", "recipients_est": 980, "tickets_deflected_est": 24}})
    event = tracker.observe("care_send_notice", {"enodeb_names": ["KKRI-0142"]}, sent)
    assert event is not None and event["track"] == 3 and event["name"] == "care_send_notice"
    assert "NTC-0001" in event["label"] and "980" in event["label"]
    assert tracker.observe("demo_advance_clock", {"minutes": 5}, "{}") is None
    assert tracker.observe("care_send_notice", {}, "oops", ok=False) is None
    odd = tracker.observe("field_dispatch", {}, "not json")  # a track tool with an odd result still lights its card
    assert odd is not None and odd["track"] == 2 and odd["label"]


class FakeHub:
    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.tools: list[Any] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        if name not in self.answers:
            raise RuntimeError(f"no answer for {name}")
        return json.dumps({"synthetic": True, "data": self.answers[name]})


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return build_test_db(tmp_path)


AS_OF = "2026-11-14T07:00:00+08:00"


def test_tracks_state_before_anything_is_done_says_what_is_waiting(db_file: Path) -> None:
    hub = FakeHub({"care_list_notices": {"notices": [], "returned": 0}, "field_list_jobs": {"jobs": [], "returned": 0}})
    state = asyncio.run(tracks_state(hub, db_file, 0, AS_OF))  # type: ignore[arg-type]
    assert [c["track"] for c in state["cards"]] == [1, 2, 3, 4, 5, 6]
    assert all(c["title"] and c["waiting"] for c in state["cards"])
    assert state["cards"][2]["numbers"]["notices_sent"] == 0 and state["cards"][1]["numbers"]["jobs"] == 0
    assert all(c["done"] is False for c in state["cards"])


def test_tracks_state_sums_notices_credits_and_energy_saved(db_file: Path) -> None:
    conn = connect(db_file, owned_tables={"energy_action", "qod_booking", "sla_credit", "sqlite_sequence"})
    try:
        conn.execute("INSERT INTO energy_action (action_id, enodeb_name, kind, from_min, to_min, kwh_saved, co2_kg_saved, approved_by, reason) "
                     "SELECT 'ENA-0001', enodeb_name, 'SLEEP', -300, -60, 12.5, 7.31, 'human', '' FROM tower LIMIT 1")
        conn.execute("INSERT INTO qod_booking (booking_id, profile_id, towers, customer, from_min, to_min, price_rm, approved_by, reason) "
                     "SELECT 'BKG-0001', profile_id, '[]', 'X (synthetic)', 100, 160, 5400.0, 'human', '' FROM qod_profile LIMIT 1")
        conn.execute("INSERT INTO sla_credit (credit_id, account_id, from_min, hours, amount_rm, issued_min, issued_at, approved_by, reason) "
                     "SELECT 'CRD-0001', account_id, 0, 2.0, 200.0, 150, '2026-11-14T09:30:00+08:00', 'human', '' FROM enterprise_account LIMIT 1")
        conn.commit()
    finally:
        conn.close()
    hub = FakeHub(
        {
            "care_list_notices": {"returned": 2, "notices": [{"recipients_est": 980, "tickets_deflected_est": 24}, {"recipients_est": 100, "tickets_deflected_est": 5}]},
            "field_list_jobs": {"returned": 1, "jobs": [{"job_id": "JOB-0001", "tech_name": "A (synthetic)", "enodeb_name": "KKRI-0142", "status": "EN_ROUTE", "eta_left_min": 60, "access": "BOAT"}]},
            "enterprise_get_revenue_at_risk": {"accounts": [{}, {}], "net_exposure_rm": 1393.0, "revenue_per_hour_rm": 310.0},
        }
    )
    state = asyncio.run(tracks_state(hub, db_file, 200, AS_OF))  # type: ignore[arg-type]
    cards = {c["track"]: c for c in state["cards"]}
    assert cards[3]["numbers"] == {**cards[3]["numbers"], "notices_sent": 2, "customers_notified": 1080, "tickets_deflected": 29}
    assert cards[5]["numbers"]["kwh_saved"] == 12.5 and cards[5]["numbers"]["co2_kg_saved"] == 7.31
    assert cards[6]["numbers"]["credits_rm"] == 200.0 and cards[6]["numbers"]["qod_booked_rm"] == 5400.0
    assert cards[2]["numbers"]["jobs"] == 1 and cards[2]["jobs"][0]["job_id"] == "JOB-0001"
    assert cards[3]["done"] is True and cards[5]["done"] is True and cards[6]["done"] is True


def test_tracks_state_shows_only_what_has_happened_by_the_clock(db_file: Path) -> None:
    conn = connect(db_file, owned_tables={"energy_action", "sqlite_sequence"})
    try:
        conn.execute("INSERT INTO energy_action (action_id, enodeb_name, kind, from_min, to_min, kwh_saved, co2_kg_saved, approved_by, reason) "
                     "SELECT 'ENA-0001', enodeb_name, 'SLEEP', 500, 600, 9.0, 5.0, 'human', '' FROM tower LIMIT 1")
        conn.commit()
    finally:
        conn.close()
    hub = FakeHub({"care_list_notices": {"notices": [], "returned": 0}, "field_list_jobs": {"jobs": [], "returned": 0}})
    state = asyncio.run(tracks_state(hub, db_file, 0, AS_OF))  # type: ignore[arg-type]
    assert state["cards"][4]["numbers"]["kwh_saved"] == 0.0  # the action is at minute 500, the clock is at 0
    later = asyncio.run(tracks_state(hub, db_file, 600, AS_OF))  # type: ignore[arg-type]
    assert later["cards"][4]["numbers"]["kwh_saved"] == 9.0


def test_a_failing_server_leaves_its_card_waiting_not_broken(db_file: Path) -> None:
    state = asyncio.run(tracks_state(FakeHub({}), db_file, 0, AS_OF))  # type: ignore[arg-type]
    assert len(state["cards"]) == 6 and all(c["done"] is False for c in state["cards"])


def test_the_clock_helper_is_importable() -> None:
    assert tracks.FLOOD_CENTRE and clock  # the module and the scenario clock are both in place