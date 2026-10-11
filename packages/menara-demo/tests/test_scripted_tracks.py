"""The six-track replay script, checked offline: it extends the incident script and survives odd results."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from menara_demo.scripted import STEPS as INCIDENT
from menara_demo.scripted_tracks import FINISHED, REJECTED, STEPS, TracksReplayModel
from menara_demo.tracks import track_for

NEW_TOOLS = {
    "energy_find_savings", "energy_apply_sleep", "energy_get_tower", "care_get_impact", "care_draft_notice", "care_send_notice",
    "enterprise_get_revenue_at_risk", "enterprise_issue_credit", "field_find_crew", "field_dispatch", "sensors_get_alerts",
    "scam_get_hotspots", "scam_get_pattern", "events_list_upcoming", "events_forecast_load", "events_capacity_plan",
    "exposure_list_profiles", "exposure_quote", "exposure_book",
}
GATED = {"energy_sleep_cells", "comms_send_notice", "enterprise_issue_credit", "workforce_create_order", "exposure_book_qod"}


def test_the_tracks_script_extends_the_incident_script() -> None:
    names = [name for name, _ in STEPS]
    incident = [name for name, _ in INCIDENT]
    position = 0
    for name in names:  # the incident steps appear in order inside the longer script
        if position < len(incident) and name == incident[position]:
            position += 1
    assert position == len(incident)
    assert set(names) >= NEW_TOOLS
    assert {track_for(n) for n in names if track_for(n)} == {1, 2, 3, 4, 5, 6}


def test_every_new_real_world_action_has_a_policy_check_just_before_it() -> None:
    for index, (name, _) in enumerate(STEPS):
        if name in {"energy_apply_sleep", "care_send_notice", "enterprise_issue_credit", "field_dispatch", "exposure_book"}:
            assert STEPS[index - 1][0] == "policy_check_action", name


def test_builders_survive_error_results_and_odd_shapes() -> None:
    for results_for in ({"error": "nope"}, {}, {"data": None}, {"data": {"candidates": "x", "accounts": [1], "events": [None]}}):
        for index, (_, build) in enumerate(STEPS):
            arguments = build([results_for] * index)
            assert isinstance(arguments, dict)


def reply_for(results: list[Any]) -> Any:
    messages = [{"role": "tool", "content": json.dumps(r)} for r in results]
    return asyncio.run(TracksReplayModel().complete(messages, []))


def test_the_model_plays_one_call_per_turn_then_finishes_and_stops_on_a_rejection() -> None:
    first = reply_for([])
    assert first.tool_calls[0].name == STEPS[0][0]
    assert reply_for([{}] * 3).tool_calls[0].name == STEPS[3][0]
    done = reply_for([{}] * len(STEPS))
    assert done.content == FINISHED and not done.tool_calls
    rejected = reply_for([{}, {"decision": "rejected_by_human"}])
    assert rejected.content == REJECTED and not rejected.tool_calls


def test_the_script_reads_tokens_and_ids_from_earlier_results() -> None:
    names = [n for n, _ in STEPS]
    sleep = names.index("energy_apply_sleep")
    results: list[Any] = [{} for _ in STEPS]
    results[0] = {"data": {"candidates": [{"enodeb_name": "TWR-A"}, {"enodeb_name": "TWR-B"}]}}
    results[1] = {"decision": "approved_by_human", "token": "tok-sleep"}
    arguments = STEPS[sleep][1](results[:sleep])
    assert arguments["enodeb_names"] == ["TWR-A", "TWR-B"] and arguments["policy_token"] == "tok-sleep"