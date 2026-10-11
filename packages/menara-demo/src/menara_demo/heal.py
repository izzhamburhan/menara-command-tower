"""The self-healing loop, made visible: which stage a tool call is, and the loop's state for the chart.

Stages: detect, diagnose, simulate, approve, apply, verify, rollback, recover. `stage_for` and `StageTracker` turn a
finished tool call into a stage event for the page. `heal_state` reads the real servers (through the hub) for the
KPI series of the overloaded neighbours, the RAN changes (tilts and their rollbacks), and the incident, so the chart is
drawn from data, not from a script. All data is synthetic.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from menara_demo.app_types import Hub

STAGES = ("detect", "diagnose", "simulate", "approve", "apply", "verify", "rollback", "recover")
THRESHOLD_PRB = 85.0
FLOOD_ANCHOR = "KKRI-0142"  # the scenario's flood tower, until an incident names another
MAX_WINDOW_MIN = 1440  # tower_get_kpi's limit
LEAD_MIN = 240
MAX_POINTS = 200

_DETECT = {"ticket_get_ticket", "ticket_cluster_by_location", "tower_get_status", "tower_get_alarms"}
_DIAGNOSE = {"ontology_blast_radius", "ontology_create_incident"}
_DIAGNOSE_PREFIXES = ("grid_", "flood_", "weather_")


def stage_for(name: str, arguments: dict[str, Any]) -> str | None:
    if name in _DETECT:
        return "detect"
    if name in _DIAGNOSE or name.startswith(_DIAGNOSE_PREFIXES):
        return "diagnose"
    if name.startswith("twin_"):
        return "simulate"
    if name == "policy_check_action":
        return "approve"
    if name in ("ran_tilt_cells", "drone_dispatch"):
        return "apply"
    if name == "tower_get_kpi":
        return "verify"
    if name == "ran_revert_change":
        return "rollback"
    if name == "ontology_update_incident" and arguments.get("status") == "RESOLVED":
        return "recover"
    return None


def _data(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    data = parsed.get("data")
    return data if isinstance(data, dict) else parsed  # the human gate answers with a flat object


class StageTracker:
    """Counts the tilt attempts of one run and words each stage event."""

    def __init__(self) -> None:
        self.attempt = 0

    def observe(self, name: str, arguments: dict[str, Any], text: str, ok: bool = True) -> dict[str, Any] | None:
        stage = stage_for(name, arguments) if ok else None
        if stage is None:
            return None
        data = _data(text)
        attempt = 0
        if name == "ran_tilt_cells":
            self.attempt += 1
        if name != "drone_dispatch" and stage in ("apply", "verify", "rollback"):
            attempt = self.attempt
        return {"stage": stage, "attempt": attempt, "label": self._label(stage, name, arguments, data, attempt)}

    @staticmethod
    def _label(stage: str, name: str, arguments: dict[str, Any], data: dict[str, Any], attempt: int) -> str:
        if stage == "apply" and name == "ran_tilt_cells":
            towers = [c.get("enodeb_name", "?") for c in arguments.get("changes") or [] if isinstance(c, dict)]
            return f"Tilt attempt {attempt}: {', '.join(towers) or 'neighbours'}"
        if stage == "apply":
            return f"Drone sent to {arguments.get('enodeb_name', 'the tower')}"
        if stage == "verify":
            peak = (data.get("summary") or {}).get("max_prb_util")
            tower = arguments.get("enodeb_name", "tower")
            return f"KPI check {tower}: peak {peak}% PRB" if peak is not None else f"KPI check {tower}"
        if stage == "rollback":
            return f"Rolled back {arguments.get('change_id', 'the change')}"
        if stage == "approve":
            decision = data.get("decision")
            return {
                "ask": "Policy: a human must approve",
                "allow": "Policy: allowed",
                "deny": "Policy: denied",
                "approved_by_human": "Policy: a human approved",
                "rejected_by_human": "Policy: a human rejected",
            }.get(str(decision), "Policy check")
        if stage == "recover":
            return "Incident resolved"
        if stage == "simulate":
            return "Simulated before acting: " + ("tilt" if "tilt" in name else "failure")
        if stage == "diagnose":
            return "Diagnose: " + name.split("_", 1)[0].replace("ontology", "blast radius and incident")
        return "Detect: " + str(arguments.get("enodeb_name") or arguments.get("ticket_id") or name)


def _thin(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(points) <= MAX_POINTS:
        return points
    step = -(-len(points) // MAX_POINTS)
    kept = points[::step]
    if kept[-1] is not points[-1]:
        kept.append(points[-1])
    return kept


def _minutes(start: datetime, stamp: str | None) -> int | None:
    return None if stamp is None else round((datetime.fromisoformat(stamp) - start).total_seconds() / 60)


async def _safe(hub: Hub, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _data(await hub.call(name, arguments))
    except Exception:
        return {}


async def heal_state(hub: Hub, clock_min: int, as_of: str) -> dict[str, Any]:
    """The loop's state at the scenario clock, read from the servers."""
    start = datetime.fromisoformat(as_of) - timedelta(minutes=clock_min)
    incidents = (await _safe(hub, "ontology_list_incidents", {})).get("incidents") or []
    latest = max(incidents, key=lambda i: datetime.fromisoformat(i["created_at"]), default=None)
    failed = latest["enodeb_name"] if latest else FLOOD_ANCHOR
    changes = (await _safe(hub, "ran_list_changes", {})).get("changes") or []
    changes = sorted(changes, key=lambda c: (c.get("applied_at") or "", c["change_id"]))  # oldest first
    changed = [t for c in changes for t in c.get("towers") or []]
    status = await _safe(hub, "tower_get_status", {"enodeb_name": failed})
    candidates = list(dict.fromkeys([n["enodeb_name"] for n in status.get("neighbours") or []] + changed))
    window = min(MAX_WINDOW_MIN, max(5, clock_min + LEAD_MIN))
    watched: list[str] = []
    series: dict[str, list[dict[str, Any]]] = {}
    for tower in candidates:
        kpi = await _safe(hub, "tower_get_kpi", {"enodeb_name": tower, "window_min": window})
        points = [{"t_min": p["t_min"], "prb": p["prb_util"]} for p in kpi.get("points") or [] if p.get("t_min") is not None]
        if points and (tower in changed or max(p["prb"] for p in points) >= THRESHOLD_PRB):
            watched.append(tower)
            series[tower] = _thin(points)
    return {
        "clock_min": clock_min,
        "failed_tower": failed,
        "failed_status": status.get("status"),
        "threshold": THRESHOLD_PRB,
        "watched": watched,
        "series": series,
        "changes": [
            {
                "change_id": c["change_id"],
                "status": c["status"],
                "applied_min": _minutes(start, c.get("applied_at")),
                "reverted_min": _minutes(start, c.get("reverted_at")),
                "towers": c.get("towers") or [],
            }
            for c in changes
        ],
        "incident": {"incident_id": latest["incident_id"], "status": latest["status"]} if latest else None,
    }