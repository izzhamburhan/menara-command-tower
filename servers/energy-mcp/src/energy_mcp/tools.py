"""energy-mcp tool logic. Plain functions over a DB connection; server.py exposes them.

Owns `energy_action` (the sleep modes that were approved and applied). Reads, read-only: `tower`, `cell`, `tower_state`,
`tower_kpi`, `tower_neighbour`, `tower_energy`, `critical_site`, `flood_extent`. All numbers are synthetic estimates.

Model: a tower draws `base_kw x (0.65 + 0.5 x load)`, a standby 35% of base when down. Night traffic is taken to be 40%
of the tower's average load. A tower may put some capacity layers to sleep between 00:00 and 06:00 when that night load
is quiet, every neighbour is up, it serves no emergency site and it is not flooded; a sleeping tower draws 35% less.
Applying a sleep mode is a real-world action and needs a signed policy token for `energy_sleep_cells`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from menara_core import clock, settings
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.geo import bbox_around, haversine_km
from menara_core.ids import parse_enodeb, target_key
from menara_core.tokens import verify_token

from energy_mcp.models import (
    Centre,
    Savings,
    SleepAction,
    SleepCandidate,
    SleepResult,
    Supply,
    TowerEnergy,
)

SOURCE = "energy-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"energy_action"})
ACTION = "energy_sleep_cells"
CO2_KG_PER_KWH = 0.585  # synthetic grid factor
SLEEPABLE_SHARE = 0.35
NIGHT_LOAD_FACTOR = 0.4
PRB_QUIET = 25.0
PRB_VERY_QUIET = 15.0
STANDBY_SHARE = 0.35
SLEEP_START_HOUR, SLEEP_END_HOUR = 0, 6
MIN_CELLS = 2
MIN_RADIUS_KM, MAX_RADIUS_KM = 0.1, 100.0
MAX_TOWERS = 20
MAX_CANDIDATES = 50
WINDOW_TEXT = "00:00 to 06:00"
URGENT_HOURS = 3.0


def draw_kw(base_kw: float, prb_util: float) -> float:
    """Power drawn at a given PRB load, before any sleep mode."""
    return round(base_kw * (0.65 + 0.5 * prb_util / 100.0), 2)


def _local_clock(conn: sqlite3.Connection) -> tuple[int, int, int]:
    """(scenario minute, local hour, local minute) at the scenario clock."""
    now = clock.now_min(conn)
    stamp = datetime.fromisoformat(clock.as_of(conn))
    return now, stamp.hour, stamp.minute


def _require_tower(conn: sqlite3.Connection, name: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT t.enodeb_name, e.base_kw, e.battery_kwh, e.has_genset, e.genset_fuel_l, e.genset_l_per_h "
        "FROM tower t JOIN tower_energy e ON e.enodeb_name = t.enodeb_name WHERE t.enodeb_name = ?",
        (name,),
    ).fetchone()
    if row is None:
        raise NotFoundError(f"Tower {name} not found")
    return row  # type: ignore[no-any-return]


def _state(conn: sqlite3.Connection, name: str, now: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT status, battery_pct, mains_ok FROM tower_state WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1",
        (name, now),
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT status, battery_pct, mains_ok FROM tower_state WHERE enodeb_name = ? ORDER BY t_min LIMIT 1", (name,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"Tower {name} has no state")
    return row  # type: ignore[no-any-return]


def _load_now(conn: sqlite3.Connection, name: str, now: int) -> float:
    row = conn.execute(
        "SELECT prb_util FROM tower_kpi WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (name, now)
    ).fetchone()
    return float(row["prb_util"]) if row else 0.0


def _night_load(conn: sqlite3.Connection, name: str) -> float:
    row = conn.execute("SELECT AVG(prb_util) AS mean FROM tower_kpi WHERE enodeb_name = ?", (name,)).fetchone()
    return round(float(row["mean"] or 0.0) * NIGHT_LOAD_FACTOR, 1)


def _active_action(conn: sqlite3.Connection, name: str, now: int) -> sqlite3.Row | None:
    return conn.execute(  # type: ignore[no-any-return]
        "SELECT action_id, to_min FROM energy_action WHERE enodeb_name = ? AND from_min <= ? AND ? < to_min ORDER BY seq DESC LIMIT 1",
        (name, now, now),
    ).fetchone()


def get_tower(conn: sqlite3.Connection, enodeb_name: str) -> Envelope[TowerEnergy]:
    """Power draw now, the supply (mains, battery, generator) and how long it lasts."""
    name = parse_enodeb(enodeb_name)
    row = _require_tower(conn, name)
    now = clock.now_min(conn)
    state = _state(conn, name, now)
    load = _load_now(conn, name, now)
    down = state["status"] == "DOWN"
    draw = round(row["base_kw"] * STANDBY_SHARE, 2) if down else draw_kw(row["base_kw"], load)
    action = _active_action(conn, name, now)
    if action is not None:
        draw = round(draw * (1 - SLEEPABLE_SHARE), 2)
    mains = bool(state["mains_ok"])
    battery_kwh = row["battery_kwh"] * state["battery_pct"] / 100.0
    fuel_hours = row["genset_fuel_l"] / row["genset_l_per_h"] if row["has_genset"] and row["genset_l_per_h"] else None
    supply: Supply
    hours_left: float | None = None
    if mains:
        supply = "MAINS"
    elif state["battery_pct"] > 0:
        supply, hours_left = "BATTERY", round(battery_kwh / max(draw, 0.01), 1)
    elif fuel_hours:
        supply, hours_left = "GENERATOR", round(fuel_hours, 1)
    else:
        supply, hours_left = "NONE", 0.0
    warnings: list[str] = []
    if not mains:
        left = f"about {hours_left:g} h" if hours_left else "no time"
        warnings.append(f"{name} has no mains power: {left} left on {supply.lower()}.")
        if hours_left is not None and hours_left < URGENT_HOURS:
            warnings.append("Urgent: under 3 hours of backup power remain.")
    data = TowerEnergy(
        enodeb_name=name, status=state["status"], supply=supply, mains_ok=mains, battery_pct=state["battery_pct"],
        load_pct=round(load, 1), base_kw=row["base_kw"], draw_kw=draw, sleeping=action is not None,
        active_action=action["action_id"] if action else None, hours_left=hours_left, has_generator=bool(row["has_genset"]),
        generator_fuel_l=row["genset_fuel_l"], generator_hours_left=round(fuel_hours, 1) if fuel_hours else None,
    )
    return wrap(conn, source=SOURCE, tool="energy_get_tower", data=data, ref=name, warnings=warnings)


def _in_flood(conn: sqlite3.Connection, lat: float, lng: float, now: int) -> bool:
    return any(
        haversine_km(lat, lng, e["lat"], e["lng"]) <= e["radius_km"]
        for e in conn.execute("SELECT lat, lng, radius_km FROM flood_extent WHERE from_min <= ?", (now,))
    )


def _assess(conn: sqlite3.Connection, name: str, now: int, remaining_hours: float) -> tuple[SleepCandidate | None, str]:
    """Can this tower sleep now? Returns the candidate, or None and the reason."""
    row = _require_tower(conn, name)
    tower = conn.execute("SELECT lat, lng FROM tower WHERE enodeb_name = ?", (name,)).fetchone()
    if _state(conn, name, now)["status"] != "UP":
        return None, "the tower is not up"
    cells = conn.execute("SELECT COUNT(*) FROM cell WHERE enodeb_name = ?", (name,)).fetchone()[0]
    if cells < MIN_CELLS:
        return None, f"it has fewer than {MIN_CELLS} cells"
    if conn.execute("SELECT 1 FROM critical_site WHERE serving_enodeb = ? AND emergency_service = 1", (name,)).fetchone():
        return None, "it serves an emergency site"
    if _in_flood(conn, tower["lat"], tower["lng"], now):
        return None, "it is inside a flood extent"
    night = _night_load(conn, name)
    if night >= PRB_QUIET:
        return None, f"its night load of {night:g}% is not quiet"
    neighbours = [r["neighbour_name"] for r in conn.execute("SELECT neighbour_name FROM tower_neighbour WHERE enodeb_name = ?", (name,))]
    if not neighbours:
        return None, "it has no neighbour to cover for it"
    if any(_state(conn, n, now)["status"] != "UP" for n in neighbours):
        return None, "a neighbour is not up"
    if _active_action(conn, name, now) is not None:
        return None, "it is already sleeping"
    kwh = round(draw_kw(row["base_kw"], night) * SLEEPABLE_SHARE * remaining_hours, 2)  # a share of the night draw
    return SleepCandidate(
        enodeb_name=name, cells=int(cells), night_load_pct=night, kwh_saved=kwh, co2_kg_saved=round(kwh * CO2_KG_PER_KWH, 2),
        risk="LOW" if night < PRB_VERY_QUIET else "MEDIUM",
    ), ""


def _remaining_hours(hour: int | None, clock_hour: int, clock_minute: int) -> tuple[int, float, bool]:
    """(hour used, hours left in the sleep window, window open)."""
    used = clock_hour if hour is None else hour
    open_ = SLEEP_START_HOUR <= used < SLEEP_END_HOUR
    minutes = clock_minute / 60.0 if hour is None else 0.0
    return used, max(0.0, SLEEP_END_HOUR - used - minutes) if open_ else 0.0, open_


def find_savings(
    conn: sqlite3.Connection, lat: float, lng: float, radius_km: float = 15.0, hour: int | None = None
) -> Envelope[Savings]:
    """Towers in a circle that can sleep some capacity layers tonight, with the energy and CO2 it saves."""
    if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
        raise InvalidInputError("Invalid centre: need -90<=lat<=90 and -180<=lng<=180")
    if not MIN_RADIUS_KM <= radius_km <= MAX_RADIUS_KM:
        raise InvalidInputError(f"radius_km must be between {MIN_RADIUS_KM} and {MAX_RADIUS_KM}")
    if hour is not None and not 0 <= hour <= 23:
        raise InvalidInputError("hour must be between 0 and 23")
    now, clock_hour, clock_minute = _local_clock(conn)
    used, remaining, window_open = _remaining_hours(hour, clock_hour, clock_minute)
    candidates: list[SleepCandidate] = []
    if window_open:
        min_lat, min_lng, max_lat, max_lng = bbox_around(lat, lng, radius_km)
        for t in conn.execute(
            "SELECT enodeb_name, lat, lng FROM tower WHERE lat BETWEEN ? AND ? AND lng BETWEEN ? AND ? ORDER BY enodeb_name",
            (max(min_lat, -90.0), min(max_lat, 90.0), max(min_lng, -180.0), min(max_lng, 180.0)),
        ).fetchall():
            if haversine_km(lat, lng, t["lat"], t["lng"]) <= radius_km:
                found, _ = _assess(conn, t["enodeb_name"], now, remaining)
                if found is not None:
                    candidates.append(found)
    candidates = sorted(candidates, key=lambda c: (-c.kwh_saved, c.enodeb_name))[:MAX_CANDIDATES]
    data = Savings(
        center=Centre(lat=lat, lng=lng), radius_km=radius_km, hour=used, window_open=window_open, window=WINDOW_TEXT,
        co2_kg_per_kwh=CO2_KG_PER_KWH, candidates=candidates, total_kwh_saved=round(sum(c.kwh_saved for c in candidates), 2),
        total_co2_kg_saved=round(sum(c.co2_kg_saved for c in candidates), 2),
    )
    warnings = [] if window_open else [f"The sleep window is {WINDOW_TEXT} local time; it is {used:02d}:00, so nothing can sleep now."]
    return wrap(conn, source=SOURCE, tool="energy_find_savings", data=data, ref=f"{lat},{lng},{radius_km}km@{used:02d}h", warnings=warnings)


def apply_sleep(conn: sqlite3.Connection, enodeb_names: list[str], policy_token: str, reason: str = "") -> Envelope[SleepResult]:
    """Put idle capacity layers to sleep until 06:00. Needs a policy token for action energy_sleep_cells on these towers."""
    if not 1 <= len(enodeb_names) <= MAX_TOWERS:
        raise InvalidInputError(f"Give between 1 and {MAX_TOWERS} towers")
    names = [parse_enodeb(n) for n in enodeb_names]
    if len(set(names)) != len(names):
        raise InvalidInputError("Each tower may be listed once")
    grant = verify_token(settings.signing_key(), policy_token, action=ACTION, target=target_key(names))
    now, clock_hour, clock_minute = _local_clock(conn)
    _, remaining, window_open = _remaining_hours(None, clock_hour, clock_minute)
    if not window_open:
        raise InvalidInputError(f"Outside the sleep window ({WINDOW_TEXT} local time)")
    assessed: list[SleepCandidate] = []
    for name in names:
        found, why = _assess(conn, name, now, remaining)
        if found is None:
            raise InvalidInputError(f"{name} cannot sleep now: {why}")
        assessed.append(found)
    end = now + round(remaining * 60)
    actions: list[SleepAction] = []
    for c in assessed:
        cursor = conn.execute(
            "INSERT INTO energy_action (enodeb_name, kind, from_min, to_min, kwh_saved, co2_kg_saved, approved_by, reason) "
            "VALUES (?, 'SLEEP', ?, ?, ?, ?, ?, ?)",
            (c.enodeb_name, now, end, c.kwh_saved, c.co2_kg_saved, grant.approved_by, reason.strip()[:300]),
        )
        action_id = f"ENA-{int(cursor.lastrowid or 0):04d}"
        conn.execute("UPDATE energy_action SET action_id = ? WHERE seq = ?", (action_id, cursor.lastrowid))
        actions.append(
            SleepAction(
                action_id=action_id, enodeb_name=c.enodeb_name, kind="SLEEP", from_min=now, to_min=end,
                kwh_saved=c.kwh_saved, co2_kg_saved=c.co2_kg_saved, approved_by=grant.approved_by,
            )
        )
    conn.commit()
    data = SleepResult(
        actions=actions, total_kwh_saved=round(sum(a.kwh_saved for a in actions), 2),
        total_co2_kg_saved=round(sum(a.co2_kg_saved for a in actions), 2),
    )
    return wrap(conn, source=SOURCE, tool="energy_apply_sleep", data=data, ref=target_key(names))
