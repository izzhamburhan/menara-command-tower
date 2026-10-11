"""Replay, six-track version: the Kuala Krai flood told across all six hackathon tracks, as a fixed script.

`TracksReplayModel` is a `ChatClient`, like `ReplayModel`. It plays the incident script (`scripted.STEPS`) unchanged and
adds the new servers around it: the night before (energy sleep), while the tower is down (care, enterprise, field,
sensors, scam) and afterwards (events and quality on demand). It reads ids, towers and signed tokens out of earlier
results, decides nothing, and every real-world action goes through the policy gate and a human. All data is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from menara_agent.loop import Reply, ToolCall

from menara_demo.scripted import STEPS as INCIDENT
from menara_demo.scripted import TOWER, _dig, _parse, _token

Results = list[Any]
Builder = Callable[[Results], dict[str, Any]]

KUALA_LUMPUR = (3.139, 101.687)
KUALA_KRAI = (5.531, 102.197)
KOTA_BHARU = (6.13, 102.24)
MIDDLE = 13  # the incident steps up to and including the drone mission; the rest of the incident comes after the middle block
PROFILE = "BROADCAST_UPLINK"
EVENT_DURATION_MIN = 180
CREDIT_HOURS = 2.0
SLEEP_TOWERS = 3
EVENT_TOWERS = 4
NIGHT_TO_T0_MIN = 312  # from 02:00 the night before to the incident clock at +12 min

_KEYS: dict[str, int] = {}
_INCIDENT_POS: list[int] = []
_ORDER: list[tuple[str, Builder]] = []


class _Remap:
    """The results the incident script expects: its own indices, mapped onto the longer run."""

    def __init__(self, results: Results) -> None:
        self._results = results

    def __getitem__(self, index: int) -> Any:
        return self._results[_INCIDENT_POS[index]]


def _at(results: Results, key: str) -> Any:
    return results[_KEYS[key]]


def _names(items: Any, key: str, limit: int) -> list[str]:
    return [str(i[key]) for i in (items or [])[:limit] if isinstance(i, dict) and key in i]


def _add(name: str, build: Builder, key: str | None = None) -> None:
    if key is not None:
        _KEYS[key] = len(_ORDER)
    _ORDER.append((name, build))


def _remapped(build: Callable[[Results], dict[str, Any]]) -> Builder:
    def wrapped(results: Results) -> dict[str, Any]:
        return build(_Remap(results))  # type: ignore[arg-type]

    return wrapped


def _incident(index: int) -> None:
    name, build = INCIDENT[index]
    _INCIDENT_POS.append(len(_ORDER))
    _ORDER.append((name, _remapped(build)))


def _policy(action: str, targets: Callable[[Results], list[str]], reason: str, key: str, confidence: float = 0.9) -> None:
    _add("policy_check_action", lambda r: {"action": action, "targets": targets(r), "confidence": confidence, "reason": reason}, key)


def _sleep_towers(r: Results) -> list[str]:
    return _names(_dig(_at(r, "savings"), "data", "candidates"), "enodeb_name", SLEEP_TOWERS)


def _account(r: Results) -> dict[str, Any]:
    accounts = _dig(_at(r, "risk"), "data", "accounts") or []
    return accounts[0] if accounts and isinstance(accounts[0], dict) else {}


def _crew(r: Results) -> dict[str, Any]:
    candidates = _dig(_at(r, "crew"), "data", "candidates") or []
    return candidates[0] if candidates and isinstance(candidates[0], dict) else {}


def _event(r: Results) -> dict[str, Any]:
    events = _dig(_at(r, "events"), "data", "events") or []
    chosen = [e for e in events if isinstance(e, dict) and "derby" in str(e.get("name", "")).lower()] or events
    return chosen[0] if chosen and isinstance(chosen[0], dict) else {}


def _event_towers(r: Results) -> list[str]:
    return _names(_dig(_at(r, "forecast"), "data", "towers"), "enodeb_name", EVENT_TOWERS)


def _bookable(r: Results) -> list[str]:
    return [str(t) for t in _dig(_at(r, "quote"), "data", "feasible_towers") or []] or _event_towers(r)


def _quote_start(r: Results) -> int:
    return max(0, int(_event(r).get("starts_in_min") or 0) - 30)


# --- the night before: track 5, sustainability -------------------------------------------------------------------
_add("energy_find_savings", lambda r: {"lat": KUALA_LUMPUR[0], "lng": KUALA_LUMPUR[1], "radius_km": 15}, "savings")
_policy("energy_sleep_cells", _sleep_towers, "Quiet towers at night: sleep idle capacity layers", "p_sleep")
_add(
    "energy_apply_sleep",
    lambda r: {"enodeb_names": _sleep_towers(r), "policy_token": _token(_at(r, "p_sleep")), "reason": "Night energy saving"},
    "sleep",
)
_add("demo_advance_clock", lambda r: {"minutes": NIGHT_TO_T0_MIN})

# --- the incident, tracks 1 and 4, up to the drone's report ------------------------------------------------------
for _i in range(MIDDLE):
    _incident(_i)

# --- while KKRI-0142 is down: tracks 5, 3, 6, 2 -------------------------------------------------------------------
_add("sensors_get_alerts", lambda r: {"lat": KUALA_KRAI[0], "lng": KUALA_KRAI[1], "radius_km": 20}, "alerts")
_add("energy_get_tower", lambda r: {"enodeb_name": TOWER}, "backup")
_add("care_get_impact", lambda r: {"enodeb_names": [TOWER]}, "impact")
_add("care_draft_notice", lambda r: {"enodeb_names": [TOWER], "kind": "OUTAGE", "language": "ms"}, "draft")
_policy("comms_send_notice", lambda r: [TOWER], "Tell the affected customers before they call", "p_notice", 0.95)
_add(
    "care_send_notice",
    lambda r: {
        "enodeb_names": [TOWER],
        "language": "ms",
        "message": str(_dig(_at(r, "draft"), "data", "message") or "Perkhidmatan terjejas akibat banjir. Kami sedang memulihkannya."),
        "policy_token": _token(_at(r, "p_notice")),
        "reason": "Customers were told before they called",
        "kind": "OUTAGE",
    },
    "notice",
)
_add("enterprise_get_revenue_at_risk", lambda r: {"enodeb_names": [TOWER]}, "risk")
_policy("enterprise_issue_credit", lambda r: [str(_account(r).get("enodeb_name") or TOWER)], "Business customers on the failed tower", "p_credit", 0.95)
_add(
    "enterprise_issue_credit",
    lambda r: {
        "account_id": str(_account(r).get("account_id") or ""),
        "hours": CREDIT_HOURS,
        "policy_token": _token(_at(r, "p_credit")),
        "reason": "SLA credit for the flood outage",
    },
    "credit",
)
_add("field_find_crew", lambda r: {"enodeb_name": TOWER, "skill": "POWER"}, "crew")
_policy("workforce_create_order", lambda r: [TOWER], "Send a power technician to the flooded site", "p_job", 0.95)
_add(
    "field_dispatch",
    lambda r: {
        "enodeb_name": TOWER,
        "tech_id": str(_crew(r).get("tech_id") or ""),
        "task": "Restore power at the flooded site and check the generator",
        "policy_token": _token(_at(r, "p_job")),
        "reason": "Mains failed; the backup is running down",
        "skill": "POWER",
        "access": "AUTO",
    },
    "job",
)
_add("scam_get_hotspots", lambda r: {"lat": KUALA_KRAI[0], "lng": KUALA_KRAI[1], "radius_km": 30}, "scams")
_add(
    "scam_get_pattern",
    lambda r: {"pattern_id": str(((_dig(_at(r, "scams"), "data", "patterns") or [{}])[0]).get("pattern_id") or "SCM-09")},
    "scam_pattern",
)

# --- the rest of the incident: the failed tilt, the rollback, the good tilt, power back ----------------------------
for _i in range(MIDDLE, len(INCIDENT)):
    _incident(_i)

# --- afterwards: tracks 4 and 6, the next big event ----------------------------------------------------------------
_add("events_list_upcoming", lambda r: {"lat": KOTA_BHARU[0], "lng": KOTA_BHARU[1], "radius_km": 30, "within_min": 4320}, "events")
_add("events_forecast_load", lambda r: {"event_id": str(_event(r).get("event_id") or "")}, "forecast")
_add("events_capacity_plan", lambda r: {"event_id": str(_event(r).get("event_id") or "")}, "plan")
_add("exposure_list_profiles", lambda r: {}, "profiles")
_add(
    "exposure_quote",
    lambda r: {"profile_id": PROFILE, "enodeb_names": _event_towers(r), "duration_min": EVENT_DURATION_MIN, "start_in_min": _quote_start(r)},
    "quote",
)
_policy("exposure_book_qod", _bookable, "Guaranteed uplink for the broadcaster at the match", "p_book", 0.95)
_add(
    "exposure_book",
    lambda r: {
        "profile_id": PROFILE,
        "enodeb_names": _bookable(r),
        "duration_min": EVENT_DURATION_MIN,
        "customer": "Kota Bharu Broadcast Co (synthetic)",
        "policy_token": _token(_at(r, "p_book")),
        "reason": "Sell the spare capacity the forecast leaves free",
        "start_in_min": _quote_start(r),
    },
    "booking",
)

STEPS: list[tuple[str, Builder]] = _ORDER

FINISHED = (
    "Replay finished (a fixed script, no model). The night before, idle capacity slept to save energy. Then the flood: an "
    "Incident, a human-approved drone, customers told before they called, business customers credited, a crew sent by boat, "
    "a failed fix rolled back and a good one applied, and power returned. Afterwards the next big match was forecast and "
    "its spare capacity sold. Every real-world action went through policy and a human. All data is synthetic."
)
REJECTED = "Replay stopped: the human rejected an action, so the script did not continue. Nothing real-world was done."


class TracksReplayModel:
    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> Reply:
        results: Results = [_parse(str(m["content"])) for m in messages if m.get("role") == "tool"]
        if results and _dig(results[-1], "decision") == "rejected_by_human":
            return Reply(REJECTED, [])
        index = len(results)
        if index >= len(STEPS):
            return Reply(FINISHED, [])
        name, build = STEPS[index]
        return Reply(None, [ToolCall(f"replay-{index}", name, build(results))])