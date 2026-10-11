"""The six hackathon tracks, made visible: which track a tool serves, and the scorecard of what each one has done.

`track_for` and `TrackTracker` turn a finished tool call into a track event for the page. `tracks_state` fills the six
cards from the servers (through the hub) and, for the two logs no read tool lists, from the read-only database, and only
counts what has happened by the scenario clock. A card that cannot be filled stays "waiting", never broken. All data is
synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from menara_core.db import connect

from menara_demo.app_types import Hub

TRACKS: dict[int, str] = {
    1: "Industry and Operations",
    2: "Workforce Productivity",
    3: "Customer Experience",
    4: "Networks and Infrastructure",
    5: "Sustainability and Smart Nation",
    6: "Revenue Streams",
}
FLOOD_CENTRE = (5.531, 102.197)  # Kuala Krai, where the scripted flood is
FLOOD_RADIUS_KM = 30.0
EVENT_CENTRE = (6.13, 102.24)  # Kota Bharu, where the scripted match is

_PREFIX_TRACK = {
    "energy_": 5, "sensors_": 5,
    "care_": 3, "scam_": 3, "user_": 3,
    "enterprise_": 6, "exposure_": 6,
    "field_": 2,
    "events_": 4, "tower_": 4, "ran_": 4, "twin_": 4, "grid_": 4, "flood_": 4, "weather_": 4, "sites_": 4,
    "ticket_": 1, "ontology_": 1, "drone_": 1, "policy_": 1,
}


def track_for(name: str) -> int | None:
    for prefix, number in _PREFIX_TRACK.items():
        if name.startswith(prefix):
            return number
    return None


def _data(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    data = parsed.get("data")
    return data if isinstance(data, dict) else parsed


def _first(data: dict[str, Any], key: str) -> dict[str, Any]:
    items = data.get(key)
    return items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}


class TrackTracker:
    """Words one track event per finished call that belongs to a track."""

    def observe(self, name: str, arguments: dict[str, Any], text: str, ok: bool = True) -> dict[str, Any] | None:
        track = track_for(name) if ok else None
        if track is None:
            return None
        try:
            label = self._label(name, arguments, _data(text))
        except Exception:
            label = ""
        return {"track": track, "name": name, "label": label or name}

    @staticmethod
    def _label(name: str, arguments: dict[str, Any], data: dict[str, Any]) -> str:
        if name == "care_send_notice":
            return f"Notice {data.get('notice_id', '')} to {data.get('recipients_est', '?')} customers, about {data.get('tickets_deflected_est', '?')} tickets avoided"
        if name == "care_get_impact":
            return f"{data.get('affected_customers', '?')} customers affected, {data.get('predicted_extra_tickets_if_silent', '?')} extra tickets if nobody is told"
        if name == "enterprise_issue_credit":
            return f"Credit {data.get('credit_id', '')} RM {data.get('amount_rm', '?')} to {data.get('account_id', '')}"
        if name == "enterprise_get_revenue_at_risk":
            return f"RM {data.get('net_exposure_rm', '?')} net exposure on {len(data.get('accounts') or [])} accounts"
        if name == "field_dispatch":
            return f"Job {data.get('job_id', '')}: {data.get('tech_name', 'a technician')} by {str(data.get('access', '')).lower()}, {data.get('eta_min', '?')} min"
        if name == "field_find_crew":
            return f"Crew for {data.get('enodeb_name', 'the tower')} by {str(data.get('access', '')).lower()}: {len(data.get('candidates') or [])} candidates"
        if name == "energy_apply_sleep":
            return f"Sleep applied: {data.get('total_kwh_saved', '?')} kWh, {data.get('total_co2_kg_saved', '?')} kg CO2 saved"
        if name == "energy_find_savings":
            return f"{len(data.get('candidates') or [])} towers can sleep: {data.get('total_kwh_saved', '?')} kWh"
        if name == "energy_get_tower":
            return f"{data.get('enodeb_name', 'Tower')} on {data.get('supply', '?')}, {data.get('hours_left', '?')} h left"
        if name == "exposure_book":
            return f"Booking {data.get('booking_id', '')} RM {data.get('price_rm', '?')} for {data.get('customer', 'a customer')}"
        if name == "exposure_quote":
            return f"Quote RM {data.get('price_rm', '?')} for {len(data.get('feasible_towers') or [])} feasible towers"
        if name in ("events_forecast_load", "events_capacity_plan"):
            return f"{data.get('name', 'Event')}: {data.get('overall_risk', '?')} load risk"
        if name == "events_list_upcoming":
            return f"{data.get('returned', '?')} upcoming events"
        if name == "sensors_get_alerts":
            alert = _first(data, "alerts")
            return f"{alert.get('name', 'Sensor')} {alert.get('status', '')}".strip() if alert else "No sensor alerts"
        if name == "scam_get_hotspots":
            top = _first(data, "patterns")
            return f"Top scam: {top.get('name', 'none')} ({top.get('reports', 0)} reports, {top.get('trend', '')})"
        if name == "ontology_create_incident":
            return f"Incident {data.get('incident_id', '')} opened on {arguments.get('enodeb_name', 'a tower')}"
        if name == "ontology_update_incident":
            return f"Incident {arguments.get('incident_id', '')} {str(arguments.get('status', 'updated')).lower()}"
        if name == "drone_dispatch":
            return f"Drone sent to {arguments.get('enodeb_name', 'the tower')}"
        if name == "drone_get_mission":
            return f"Drone mission {data.get('mission_id', '')} {str(data.get('status', '')).replace('_', ' ').lower()}".strip()
        if name == "policy_check_action":
            return f"Policy for {arguments.get('action', 'an action')}: {data.get('decision', '?')}"
        if name == "care_draft_notice":
            return f"Draft notice ({data.get('language', '?')}): {data.get('recipients_est', '?')} recipients, RM {data.get('cost_rm', '?')}"
        if name == "scam_get_pattern":
            return f"{data.get('name', 'Pattern')}: {data.get('severity', '?')} severity"
        if name == "exposure_list_profiles":
            return f"{len(data.get('profiles') or [])} quality-on-demand profiles"
        if name == "scam_estimate_protection":
            return f"A shield would protect {data.get('customers_protected', '?')} customers"
        return ""


async def _safe(hub: Hub, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        return _data(await hub.call(name, arguments))
    except Exception:
        return {}


def _sum_db(db_file: Path, query: str, arguments: tuple[Any, ...]) -> tuple[float, float]:
    conn = connect(db_file)
    try:
        row = conn.execute(query, arguments).fetchone()
        return (float(row[0]), float(row[1]))
    except Exception:
        return (0.0, 0.0)
    finally:
        conn.close()


def _card(track: int, waiting: str, done: bool, numbers: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"track": track, "title": TRACKS[track], "waiting": waiting, "done": done, "numbers": numbers, **extra}


async def tracks_state(hub: Hub, db_file: Path, clock_min: int, as_of: str) -> dict[str, Any]:
    """The six cards at the scenario clock."""
    del as_of  # kept so the caller reads like heal_state; the clock minute is what the cards need
    notices = await _safe(hub, "care_list_notices", {"limit": 200})
    jobs = await _safe(hub, "field_list_jobs", {"limit": 50})
    risk = await _safe(hub, "enterprise_get_revenue_at_risk", {"lat": FLOOD_CENTRE[0], "lng": FLOOD_CENTRE[1], "radius_km": FLOOD_RADIUS_KM})
    incidents = (await _safe(hub, "ontology_list_incidents", {})).get("incidents") or []
    missions = (await _safe(hub, "drone_list_missions", {})).get("missions") or []
    alerts = await _safe(hub, "sensors_get_alerts", {"lat": FLOOD_CENTRE[0], "lng": FLOOD_CENTRE[1], "radius_km": 20.0})
    scam = await _safe(hub, "scam_get_hotspots", {"lat": FLOOD_CENTRE[0], "lng": FLOOD_CENTRE[1], "radius_km": FLOOD_RADIUS_KM})
    events = await _safe(hub, "events_list_upcoming", {"lat": EVENT_CENTRE[0], "lng": EVENT_CENTRE[1], "radius_km": 60.0, "within_min": 4320})

    sent = notices.get("notices") or []
    notified = sum(int(n.get("recipients_est") or 0) for n in sent)
    deflected = sum(int(n.get("tickets_deflected_est") or 0) for n in sent)
    kwh, co2 = _sum_db(db_file, "SELECT COALESCE(SUM(kwh_saved), 0), COALESCE(SUM(co2_kg_saved), 0) FROM energy_action WHERE from_min <= ?", (clock_min,))
    booked, bookings = _sum_db(db_file, "SELECT COALESCE(SUM(price_rm), 0), COUNT(*) FROM qod_booking", ())
    credits, credit_count = _sum_db(db_file, "SELECT COALESCE(SUM(amount_rm), 0), COUNT(*) FROM sla_credit WHERE issued_min <= ?", (clock_min,))
    job_list = [j for j in jobs.get("jobs") or [] if isinstance(j, dict)]
    top_alert = _first(alerts, "alerts")
    top_scam = _first(scam, "patterns")
    next_event = _first(events, "events")
    forecast = await _safe(hub, "events_forecast_load", {"event_id": next_event["event_id"]}) if next_event.get("event_id") else {}
    incident = incidents[0] if incidents and isinstance(incidents[0], dict) else {}

    cards = [
        _card(1, "Waiting for an incident to run.", bool(incident),
              {"incidents": len(incidents), "drone_missions": len(missions), "incident_status": incident.get("status")}),
        _card(2, "Waiting for a crew to be sent.", bool(job_list),
              {"jobs": len(job_list), "next_eta_min": job_list[0].get("eta_left_min") if job_list else None},
              jobs=[{k: j.get(k) for k in ("job_id", "tech_name", "enodeb_name", "status", "eta_left_min", "access")} for j in job_list[:5]]),
        _card(3, "Waiting for customers to be told.", bool(sent),
              {"notices_sent": len(sent), "customers_notified": notified, "tickets_deflected": deflected,
               "top_scam": top_scam.get("name"), "top_scam_reports": top_scam.get("reports", 0)}),
        _card(4, "Waiting for the network to be checked.", bool(missions or incident),
              {"next_event": next_event.get("name"), "next_event_attendance": next_event.get("attendance", 0), "next_event_risk": forecast.get("overall_risk")}),
        _card(5, "Waiting for a saving to be applied.", kwh > 0,
              {"kwh_saved": round(kwh, 2), "co2_kg_saved": round(co2, 2), "water_alert": top_alert.get("status"),
               "water_alert_minutes_to_danger": top_alert.get("projected_min_to_danger")}),
        _card(6, "Waiting for credits or bookings.", bookings > 0 or credit_count > 0,
              {"net_exposure_rm": float(risk.get("net_exposure_rm") or 0), "credits_rm": credits, "credits": int(credit_count),
               "revenue_per_hour_rm": float(risk.get("revenue_per_hour_rm") or 0), "qod_booked_rm": booked, "bookings": int(bookings)}),
    ]
    return {"clock_min": clock_min, "cards": cards}