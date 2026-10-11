"""What the map should show for a tool result, so the Story tab is not only text.

`effects_for` turns one tool call into a few drawable effects. Tower and site positions come from the demo's
read-only database, flood and ticket positions from the server's own result; nothing comes from the model's words.
It never raises: an unknown tool, an error text or an odd shape just gives no effects. All data is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from menara_core import settings
from menara_core.db import connect
from menara_core.scenario import load_scenario

Effect = dict[str, Any]

MAX_PINS = 40
HIGH_PRB = 85.0
GAUGE_KM = 1.5
GAUGE_TONE = {"DANGER": "bad", "WARNING": "warn"}
BOOKING_KM = 2.0
RISK_TONE = {"HIGH": "bad", "MEDIUM": "warn", "LOW": "ok"}


class _Places:
    """Tower and site positions from the read-only database."""

    def __init__(self, db_file: Path) -> None:
        self._conn = connect(db_file)

    def close(self) -> None:
        self._conn.close()

    def tower(self, name: str) -> tuple[float, float] | None:
        row = self._conn.execute("SELECT lat, lng FROM tower WHERE enodeb_name = ?", (name.removeprefix("SITE-"),)).fetchone()
        return (float(row["lat"]), float(row["lng"])) if row else None

    def site(self, site_id: str) -> tuple[float, float] | None:
        row = self._conn.execute("SELECT lat, lng FROM critical_site WHERE critical_site_id = ?", (site_id,)).fetchone()
        return (float(row["lat"]), float(row["lng"])) if row else None


    def technician(self, tech_id: str) -> tuple[float, float] | None:
        row = self._conn.execute("SELECT lat, lng FROM technician WHERE tech_id = ?", (tech_id,)).fetchone()
        return (float(row["lat"]), float(row["lng"])) if row else None

    def sensor(self, sensor_id: str) -> tuple[float, float] | None:
        row = self._conn.execute("SELECT lat, lng FROM iot_sensor WHERE sensor_id = ?", (sensor_id,)).fetchone()
        return (float(row["lat"]), float(row["lng"])) if row else None

    def event(self, event_id: str) -> tuple[float, float, float] | None:
        row = self._conn.execute("SELECT lat, lng, radius_km FROM crowd_event WHERE event_id = ?", (event_id,)).fetchone()
        return (float(row["lat"]), float(row["lng"]), float(row["radius_km"])) if row else None


def _effect(kind: str, position: tuple[float, float], label: str, tone: str, **extra: Any) -> Effect:
    return {"kind": kind, "lat": position[0], "lng": position[1], "label": label, "tone": tone, **extra}


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _tower_names(arguments: dict[str, Any], data: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("enodeb_name", "site"):
        if isinstance(arguments.get(key), str):
            names.append(arguments[key])
    for target in arguments.get("targets") or []:
        if isinstance(target, str):
            names.append(target)
    for change in arguments.get("changes") or []:
        if isinstance(change, dict) and isinstance(change.get("enodeb_name"), str):
            names.append(change["enodeb_name"])
    if not names:
        names += [t for t in data.get("towers") or [] if isinstance(t, str)]
        if isinstance(data.get("enodeb_name"), str):
            names.append(data["enodeb_name"])
    return list(dict.fromkeys(names))


def _tower_tone(name: str, data: dict[str, Any]) -> str:
    if name == "tower_get_status":
        if data.get("status") == "DOWN":
            return "bad"
        prb = _number((data.get("latest_kpi") or {}).get("prb_util"))
        return "warn" if (prb is not None and prb >= HIGH_PRB) or data.get("status") == "DEGRADED" else "ok"
    if name == "tower_get_kpi":
        prb = _number((data.get("summary") or {}).get("max_prb_util"))
        return "warn" if prb is not None and prb >= HIGH_PRB else "ok"
    return "info"


def _towers(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    tone = _tower_tone(tool, data)
    effects: list[Effect] = []
    for name in _tower_names(arguments, data):
        position = places.tower(name)
        if position is not None:
            status = f" {data['status']}" if tool == "tower_get_status" and isinstance(data.get("status"), str) else ""
            effects.append(_effect("focus", position, f"{name}{status}", tone))
    return effects


def _blast(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    origin = data.get("origin")
    if not isinstance(origin, dict) or not isinstance(origin.get("enodeb_name"), str):
        return []
    centre = places.tower(origin["enodeb_name"])
    radius = _number(data.get("radius_km"))
    if centre is None or radius is None:
        return []
    effects = [_effect("ring", centre, f"{origin['enodeb_name']} blast radius {radius:g} km", "bad", radius_km=radius)]
    pins: list[Effect] = []
    sites = data.get("critical_sites")
    for site in sites if isinstance(sites, list) else []:
        position = places.site(str(site.get("critical_site_id"))) if isinstance(site, dict) else None
        if position is not None:
            tone = "bad" if site.get("emergency_service") else "warn"
            pins.append(_effect("pin", position, f"{site.get('name', 'Site')}", tone, icon=str(site.get("kind", "")).lower()))
    towers = data.get("at_risk_towers")
    for tower in towers if isinstance(towers, list) else []:
        position = places.tower(str(tower.get("enodeb_name"))) if isinstance(tower, dict) else None
        if position is not None:
            tone = "bad" if tower.get("status") == "DOWN" else "warn"
            pins.append(_effect("pin", position, f"{tower['enodeb_name']} at risk", tone, icon="tower"))
    return effects + pins[:MAX_PINS]


def _gauge(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    lat, lng = _number(data.get("lat")), _number(data.get("lng"))
    if lat is None or lng is None:
        return []
    tone = GAUGE_TONE.get(str(data.get("status")), "ok")
    level = _number(data.get("level_m"))
    label = f"{data.get('gauge_id', 'Gauge')} {level:g} m {data.get('status', '')}".strip() if level is not None else str(data.get("gauge_id", "Gauge"))
    return [_effect("area", (lat, lng), label, tone, radius_km=GAUGE_KM)]


def _flood_point(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    lat, lng = _number(data.get("lat")), _number(data.get("lng"))
    if lat is None or lng is None:
        return []
    if data.get("inside_flood") is True and (radius := _number(data.get("extent_radius_km"))) is not None:
        depth = _number(data.get("depth_m"))
        suffix = f", {depth:g} m deep" if depth is not None else ""
        return [_effect("area", (lat, lng), f"{data.get('extent_name', 'Flood extent')}{suffix}", "bad", radius_km=radius)]
    return [_effect("pin", (lat, lng), "Outside the flood extent", "ok")]


def _depot_position(depot_name: str) -> tuple[float, float] | None:
    for depot in load_scenario(settings.default_scenario_path()).drone.depots:
        if depot.name == depot_name:
            return (depot.lat, depot.lng)
    return None


def _drone(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    tower = data.get("enodeb_name") if isinstance(data.get("enodeb_name"), str) else arguments.get("enodeb_name")
    position = places.tower(tower) if isinstance(tower, str) else None
    if position is None:
        return []
    progress = _number(data.get("progress_pct"))
    label = f"{data.get('drone_id', 'Drone')} {str(data.get('status', '')).replace('_', ' ').lower()}".strip()
    if progress is not None:
        label += f" {progress:g}%"
    effects = [_effect("pin", position, label, "info", icon="drone")]
    depot = _depot_position(str(data.get("depot_name", "")))
    if depot is not None:
        effects.append(_effect("link", depot, f"{data.get('depot_name')} to {tower}", "info", to=[position[0], position[1]]))
    return effects


def _tickets(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    tickets = data.get("tickets")
    effects: list[Effect] = []
    for ticket in tickets if isinstance(tickets, list) else []:
        if not isinstance(ticket, dict):
            continue
        lat, lng = _number(ticket.get("lat")), _number(ticket.get("lng"))
        if lat is not None and lng is not None:
            effects.append(_effect("pin", (lat, lng), f"{ticket.get('ticket_id', 'Ticket')} {ticket.get('location_text', '')}".strip(), "warn", icon="ticket"))
    return effects[:MAX_PINS]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _field_dispatch(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    tower = data.get("enodeb_name") if isinstance(data.get("enodeb_name"), str) else arguments.get("enodeb_name")
    position = places.tower(tower) if isinstance(tower, str) else None
    if position is None:
        return []
    access = str(data.get("access", "ROAD")).lower()
    effects = [_effect("pin", position, f"{data.get('job_id', 'Job')} {data.get('tech_name', 'technician')} by {access}", "info", icon="crew")]
    home = places.technician(str(data.get("tech_id") or arguments.get("tech_id") or ""))
    if home is not None:
        effects.append(_effect("link", home, f"{data.get('tech_name', 'Technician')} to {tower} by {access}", "info", to=[position[0], position[1]]))
    return effects


def _energy_sleep(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    effects: list[Effect] = []
    for action in _dicts(data.get("actions")):
        position = places.tower(str(action.get("enodeb_name", "")))
        if position is not None:
            effects.append(_effect("focus", position, f"{action.get('action_id', 'Sleep')} asleep, {action.get('kwh_saved', '?')} kWh saved", "ok"))
    return effects[:MAX_PINS]


def _energy_savings(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    effects: list[Effect] = []
    for candidate in _dicts(data.get("candidates")):
        position = places.tower(str(candidate.get("enodeb_name", "")))
        if position is not None:
            effects.append(_effect("pin", position, f"{candidate['enodeb_name']} can sleep, {candidate.get('kwh_saved', '?')} kWh", "ok", icon="tower"))
    return effects[:MAX_PINS]


def _exposure_book(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    effects: list[Effect] = []
    for name in _list(data.get("towers")):
        position = places.tower(name) if isinstance(name, str) else None
        if position is not None:
            effects.append(_effect("area", position, f"{data.get('booking_id', 'Booking')} reserved at {name}", "ok", radius_km=BOOKING_KM))
    return effects[:MAX_PINS]


def _sensor_alerts(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    effects: list[Effect] = []
    for alert in _dicts(data.get("alerts")):
        position = places.sensor(str(alert.get("sensor_id", "")))
        if position is not None:
            tone = GAUGE_TONE.get(str(alert.get("status")), "ok")
            effects.append(_effect("pin", position, f"{alert.get('name', 'Sensor')} {alert.get('value', '')} {alert.get('unit', '')} {alert.get('status', '')}".strip(), tone, icon="sensor"))
    return effects[:MAX_PINS]


def _event_forecast(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    venue = places.event(str(data.get("event_id", "")))
    if venue is None:
        return []
    risk = str(data.get("overall_risk", ""))
    effects = [_effect("ring", (venue[0], venue[1]), f"{data.get('name', 'Event')}: {risk} load risk", RISK_TONE.get(risk, "info"), radius_km=venue[2])]
    for tower in _dicts(data.get("towers")):
        position = places.tower(str(tower.get("enodeb_name", "")))
        if position is not None:
            effects.append(_effect("pin", position, f"{tower['enodeb_name']} {tower.get('risk', '')}".strip(), RISK_TONE.get(str(tower.get("risk")), "info"), icon="tower"))
    return effects[:MAX_PINS]


def _care_impact(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    effects: list[Effect] = []
    for name in _list(data.get("affected_towers")):
        position = places.tower(name) if isinstance(name, str) else None
        if position is not None:
            effects.append(_effect("pin", position, f"{name} affected, {data.get('affected_customers', '?')} customers", "warn", icon="tower"))
    return effects[:MAX_PINS]


def _enterprise_risk(places: _Places, tool: str, arguments: dict[str, Any], data: dict[str, Any]) -> list[Effect]:
    effects: list[Effect] = []
    for account in _dicts(data.get("accounts")):
        position = places.tower(str(account.get("enodeb_name", "")))
        if position is not None:
            tone = "bad" if account.get("status") == "DOWN" else "warn"
            effects.append(_effect("pin", position, f"{account.get('name', 'Account')} {account.get('status', '')}".strip(), tone, icon="business"))
    return effects[:MAX_PINS]


Handler = Callable[[_Places, str, dict[str, Any], dict[str, Any]], list[Effect]]
HANDLERS: dict[str, Handler] = {
    "ontology_blast_radius": _blast,
    "flood_get_gauge": _gauge,
    "flood_check_point": _flood_point,
    "drone_dispatch": _drone,
    "drone_get_mission": _drone,
    "ticket_cluster_by_location": _tickets,
    "field_dispatch": _field_dispatch,
    "energy_apply_sleep": _energy_sleep,
    "energy_find_savings": _energy_savings,
    "exposure_book": _exposure_book,
    "sensors_get_alerts": _sensor_alerts,
    "events_forecast_load": _event_forecast,
    "events_capacity_plan": _event_forecast,
    "care_get_impact": _care_impact,
    "enterprise_get_revenue_at_risk": _enterprise_risk,
}
NO_MAP = {"user_get_trail", "user_get_serving_cell", "user_get_experience", "user_list_in_area", "user_list_on_tower"}


def effects_for(db_file: Path, name: str, arguments: dict[str, Any], result_text: str) -> list[Effect]:
    try:
        parsed = json.loads(result_text)
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, dict) or name in NO_MAP:
            return []
        places = _Places(db_file)
        try:
            handler = HANDLERS.get(name)
            return handler(places, name, arguments, data) if handler else _towers(places, name, arguments, data)
        finally:
            places.close()
    except Exception:
        return []