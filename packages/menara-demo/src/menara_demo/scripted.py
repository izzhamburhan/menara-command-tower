"""Replay: the incident story as a fixed script instead of a model.

`ReplayModel` is a `ChatClient`. It returns the next scripted tool call and reads earlier results (ids, signed
tokens) out of the conversation, so it runs through the very same gate, clock tool and real MCP servers as a live
model. It decides nothing: use it for a repeatable demo or when there is no model key. All data is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from menara_agent.loop import Reply, ToolCall

NEIGHBOURS = ["KKRI-0143", "KKRI-0144"]
TILT = [{"enodeb_name": name, "tilt_delta_deg": 4.0} for name in NEIGHBOURS]
TOWER = "KKRI-0142"

Results = list[Any]


def _dig(value: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _token(result: Any) -> str:
    """The token from a human approval (flat) or an auto-allow (inside data)."""
    return str(_dig(result, "token") or _dig(result, "data", "token") or "")


def _incident_id(results: Results) -> str:
    incidents = _dig(results[7], "data", "incidents") or []
    return str(incidents[0]["incident_id"]) if incidents else "INC-0001"


def _ticket_ids(results: Results) -> list[str]:
    return [t["ticket_id"] for t in _dig(results[1], "data", "tickets") or []]


Step = tuple[str, Callable[[Results], dict[str, Any]]]

STEPS: list[Step] = [
    ("ticket_get_ticket", lambda r: {"ticket_id": "TK-88213"}),
    ("ticket_cluster_by_location", lambda r: {"ticket_id": "TK-88213", "radius_km": 15, "window_min": 30}),
    ("tower_get_status", lambda r: {"enodeb_name": TOWER}),
    ("grid_get_tower_power", lambda r: {"enodeb_name": TOWER}),
    ("flood_get_gauge", lambda r: {"gauge_id": "GAUGE-KKRI-01"}),
    ("ontology_blast_radius", lambda r: {"site": TOWER}),
    (
        "ontology_create_incident",
        lambda r: {
            "enodeb_name": TOWER,
            "cause": "FLOOD",
            "cause_confidence": 0.93,
            "summary": "Tower down: feeder tripped, river above danger level, heavy rain. Replay of the scripted story.",
            "ticket_ids": _ticket_ids(r),
        },
    ),
    ("ontology_list_incidents", lambda r: {"enodeb_name": TOWER}),
    ("twin_simulate_tilt", lambda r: {"changes": TILT}),
    ("policy_check_action", lambda r: {"action": "drone_dispatch", "targets": [TOWER], "confidence": 0.93, "reason": "Check the access road and genset"}),
    ("drone_dispatch", lambda r: {"enodeb_name": TOWER, "policy_token": _token(r[9]), "reason": "Check the access road and genset"}),
    ("demo_advance_clock", lambda r: {"minutes": 65}),
    ("drone_get_mission", lambda r: {"mission_id": _dig(r[10], "data", "mission_id") or "MIS-0001"}),
    ("policy_check_action", lambda r: {"action": "ran_tilt_cells", "targets": NEIGHBOURS, "confidence": 0.93, "reason": "Simulation recommends it"}),
    ("ran_tilt_cells", lambda r: {"changes": TILT, "policy_token": _token(r[13]), "reason": "Relieve the overloaded neighbours"}),
    ("tower_get_kpi", lambda r: {"enodeb_name": "KKRI-0143", "window_min": 5}),
    ("tower_get_kpi", lambda r: {"enodeb_name": "KKRI-0144", "window_min": 5}),
    ("policy_check_action", lambda r: {"action": "ran_revert_tilt", "targets": NEIGHBOURS, "confidence": 0.99, "reason": "KKRI-0143 did not improve"}),
    ("ran_revert_change", lambda r: {"change_id": _dig(r[14], "data", "change_id") or "CHG-0001", "policy_token": _token(r[17]), "reason": "Fix did not improve KPIs"}),
    ("policy_check_action", lambda r: {"action": "ran_tilt_cells", "targets": NEIGHBOURS, "confidence": 0.93, "reason": "Second attempt"}),
    ("ran_tilt_cells", lambda r: {"changes": TILT, "policy_token": _token(r[19]), "reason": "Second attempt"}),
    ("tower_get_kpi", lambda r: {"enodeb_name": "KKRI-0143", "window_min": 5}),
    ("ontology_update_incident", lambda r: {"incident_id": _incident_id(r), "status": "MITIGATING", "note": "Neighbours re-tilted, load relieved"}),
    ("demo_advance_clock", lambda r: {"minutes": 300}),
    ("tower_get_status", lambda r: {"enodeb_name": TOWER}),
    ("policy_check_action", lambda r: {"action": "ran_revert_tilt", "targets": NEIGHBOURS, "confidence": 0.99, "reason": "Power is back; restore the original tilt"}),
    ("ran_revert_change", lambda r: {"change_id": _dig(r[20], "data", "change_id") or "CHG-0002", "policy_token": _token(r[25]), "reason": "Power is back"}),
    ("ontology_update_incident", lambda r: {"incident_id": _incident_id(r), "status": "RESOLVED", "note": "Power restored, tilt rolled back"}),
]

FINISHED = (
    "Replay finished (a fixed script, no model). The story: flood cut power to KKRI-0142, an Incident was recorded, a "
    "human-approved drone inspected the site, a first tilt of the neighbours failed its KPI check and was rolled back, "
    "a second tilt worked, power returned, the tilt was undone and the Incident resolved. All data is synthetic."
)
REJECTED = "Replay stopped: the human rejected an action, so the script did not continue. Nothing real-world was done."


def _parse(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return {"error": text}


class ReplayModel:
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        results: Results = [_parse(str(m["content"])) for m in messages if m.get("role") == "tool"]
        if results and _dig(results[-1], "decision") == "rejected_by_human":
            return Reply(REJECTED, [])
        index = len(results)
        if index >= len(STEPS):
            return Reply(FINISHED, [])
        name, build = STEPS[index]
        return Reply(None, [ToolCall(f"replay-{index}", name, build(results))])