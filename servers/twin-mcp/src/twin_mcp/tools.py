"""twin-mcp tool logic.

A deliberately simple digital twin (formulas live in menara_core.network_model). It reads KPIs, neighbours,
subscribers and critical sites read-only and writes only twin_simulation. Always simulate before acting.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, cast

from menara_core import clock, kpi_overlay, network_model
from menara_core.envelope import Envelope, wrap
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.ids import SITE_RE, parse_enodeb, parse_simulation_id

from twin_mcp.models import (
    FailureSimulation,
    LoadPrediction,
    SimulationRecord,
    TiltChange,
    TiltSimulation,
    TowerStatus,
)

SOURCE = "twin-mcp"
OWNED_TABLES: frozenset[str] = frozenset({"twin_simulation"})
MAX_CHANGES = 20


# ---------- lookups ----------


def _tower(conn: sqlite3.Connection, value: str) -> str:
    text = value.strip()
    name = text[len("SITE-") :] if SITE_RE.match(text) else parse_enodeb(text)
    if conn.execute("SELECT 1 FROM tower WHERE enodeb_name = ?", (name,)).fetchone() is None:
        raise NotFoundError(f"Tower {name} not found")
    return name


def _status(conn: sqlite3.Connection, name: str, now: int) -> TowerStatus:
    row = conn.execute(
        "SELECT status FROM tower_state WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (name, now)
    ).fetchone()
    return cast(TowerStatus, row["status"]) if row else "UNKNOWN"


def _current_prb(conn: sqlite3.Connection, name: str, now: int) -> float | None:
    row = conn.execute(
        "SELECT * FROM tower_kpi WHERE enodeb_name = ? AND t_min <= ? ORDER BY t_min DESC LIMIT 1", (name, now)
    ).fetchone()
    if row is None:
        return None
    return kpi_overlay.adjust(conn, name, row["t_min"], row["prb_util"], row["drop_rate"], row["throughput_mbps"])[0]


def _last_loaded_prb(conn: sqlite3.Connection, name: str, now: int) -> float | None:
    row = conn.execute(
        "SELECT t_min, prb_util FROM tower_kpi WHERE enodeb_name = ? AND t_min <= ? AND prb_util > 0 "
        "ORDER BY t_min DESC LIMIT 1",
        (name, now),
    ).fetchone()
    return float(row["prb_util"]) if row else None


def _neighbours(conn: sqlite3.Connection, name: str) -> list[tuple[str, float]]:
    return [
        (r["neighbour_name"], float(r["distance_km"]))
        for r in conn.execute(
            "SELECT neighbour_name, distance_km FROM tower_neighbour WHERE enodeb_name = ? ORDER BY distance_km", (name,)
        )
    ]


def _subscribers(conn: sqlite3.Connection, name: str) -> int:
    row = conn.execute("SELECT subscribers_est FROM tower_subscribers WHERE enodeb_name = ?", (name,)).fetchone()
    return int(row["subscribers_est"]) if row else 0


def _weights(candidates: list[tuple[str, float]]) -> dict[str, float]:
    inverse = {name: 1.0 / max(dist, 0.1) for name, dist in candidates}
    total = sum(inverse.values())
    return {name: value / total for name, value in inverse.items()} if total else {}


def _store(conn: sqlite3.Connection, kind: str, params: dict[str, Any], build: Any) -> str:
    """Insert a row to get an id, build the result with it, then save the result."""
    stamp = clock.as_of(conn)
    cursor = conn.execute(
        "INSERT INTO twin_simulation (kind, at, params, result) VALUES (?, ?, ?, '{}')",
        (kind, stamp, json.dumps(params, sort_keys=True)),
    )
    sim_id = f"SIM-{int(cursor.lastrowid or 0):04d}"
    result = build(sim_id)
    conn.execute(
        "UPDATE twin_simulation SET sim_id = ?, result = ? WHERE seq = ?",
        (sim_id, json.dumps(result.model_dump(mode="json"), sort_keys=True), cursor.lastrowid),
    )
    conn.commit()
    return sim_id


# ---------- simulate_failure ----------


def simulate_failure(conn: sqlite3.Connection, site: str) -> Envelope[FailureSimulation]:
    """What happens to the neighbours, subscribers and critical sites if this tower goes down."""
    name = _tower(conn, site)
    now = clock.now_min(conn)
    origin_status = _status(conn, name, now)
    already_down = origin_status == "DOWN"
    load = _last_loaded_prb(conn, name, now)
    neighbours = _neighbours(conn, name)
    live = [(n, d) for n, d in neighbours if _status(conn, n, now) != "DOWN"]
    weights = _weights(live)

    predictions: list[LoadPrediction] = []
    for other, distance in neighbours:
        status = _status(conn, other, now)
        current = _current_prb(conn, other, now)
        predicted = current
        if current is not None and not already_down and status != "DOWN" and load is not None:
            gain = load * network_model.FAILOVER_SHARE * network_model.FAILOVER_GAIN * weights.get(other, 0.0)
            predicted = round(min(100.0, current + gain), 1)
        predictions.append(
            LoadPrediction(
                enodeb_name=other,
                status=status,
                distance_km=round(distance, 2),
                current_prb=current,
                predicted_prb=predicted,
                change_points=round(predicted - current, 1) if predicted is not None and current is not None else None,
                overloaded=predicted is not None and predicted >= network_model.OVERLOAD_PRB,
            )
        )
    overloaded = [p for p in predictions if p.overloaded]
    sites = conn.execute(
        "SELECT critical_site_id, emergency_service FROM critical_site WHERE serving_enodeb = ? ORDER BY critical_site_id",
        (name,),
    ).fetchall()
    subs_at_risk = sum(_subscribers(conn, p.enodeb_name) for p in overloaded)

    if already_down:
        advice = "The tower is already DOWN; neighbour loads shown are the observed KPIs, which already include the failover."
    elif not live:
        advice = "No live neighbour can absorb the traffic: expect an outage for every subscriber on this tower."
    elif overloaded:
        advice = f"{len(overloaded)} neighbour(s) would overload. Pre-position relief (tilt or steering) before this tower fails."
    else:
        advice = "Neighbours can absorb the traffic without overloading."

    def build(sim_id: str) -> FailureSimulation:
        return FailureSimulation(
            sim_id=sim_id,
            origin=name,
            already_down=already_down,
            load_before_prb=load,
            subscribers_impacted=_subscribers(conn, name),
            emergency_sites_affected=sum(int(s["emergency_service"]) for s in sites),
            critical_sites_affected=[s["critical_site_id"] for s in sites],
            neighbours=predictions,
            overloaded_count=len(overloaded),
            subscribers_at_overload_risk=subs_at_risk,
            recommendation=advice,
        )

    sim_id = _store(conn, "failure", {"site": name, "now_min": now}, build)
    record = _result(conn, sim_id, FailureSimulation)
    warnings = ["The tower is already DOWN; predictions equal the observed KPIs"] if already_down else []
    return wrap(conn, source=SOURCE, tool="twin_simulate_failure", data=record, ref=sim_id, warnings=warnings)


# ---------- simulate_tilt ----------


def simulate_tilt(conn: sqlite3.Connection, changes: list[dict[str, Any]]) -> Envelope[TiltSimulation]:
    """Predict the load on tilted towers and on the neighbours that pick up what they shed."""
    if not changes:
        raise InvalidInputError("changes must not be empty")
    if len(changes) > MAX_CHANGES:
        raise InvalidInputError(f"at most {MAX_CHANGES} tilt changes per simulation")
    parsed: list[TiltChange] = []
    for item in changes:
        try:
            delta = float(item["tilt_delta_deg"])
            raw = str(item["enodeb_name"])
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidInputError("each change needs enodeb_name and a numeric tilt_delta_deg") from exc
        if abs(delta) > network_model.MAX_TILT_DELTA_DEG:
            raise InvalidInputError(f"tilt_delta_deg must be within +/-{network_model.MAX_TILT_DELTA_DEG:g}")
        parsed.append(TiltChange(enodeb_name=_tower(conn, raw), tilt_delta_deg=delta))
    names = [c.enodeb_name for c in parsed]
    if len(set(names)) != len(names):
        raise InvalidInputError("each tower may appear once per simulation")

    now = clock.now_min(conn)
    tilted: list[LoadPrediction] = []
    coverage: dict[str, float] = {}
    spill: dict[str, float] = {}
    reasons: list[str] = []
    for change in parsed:
        current = _current_prb(conn, change.enodeb_name, now)
        predicted = network_model.predicted_prb(current, change.tilt_delta_deg) if current is not None else None
        loss = network_model.coverage_loss_pct(change.tilt_delta_deg)
        coverage[change.enodeb_name] = loss
        status = _status(conn, change.enodeb_name, now)
        tilted.append(
            LoadPrediction(
                enodeb_name=change.enodeb_name,
                status=status,
                distance_km=None,
                current_prb=current,
                predicted_prb=predicted,
                change_points=round(predicted - current, 1) if predicted is not None and current is not None else None,
                overloaded=predicted is not None and predicted >= network_model.OVERLOAD_PRB,
            )
        )
        if loss > network_model.MAX_COVERAGE_LOSS_PCT:
            reasons.append(f"{change.enodeb_name}: coverage loss {loss:g}% exceeds {network_model.MAX_COVERAGE_LOSS_PCT:g}%")
        if predicted is not None and predicted >= network_model.OVERLOAD_PRB:
            reasons.append(f"{change.enodeb_name}: still overloaded at {predicted:g}% PRB")
        if current is not None and predicted is not None and current > predicted:
            shed = (current - predicted) * network_model.OFFLOAD_SPILL
            live = [(n, d) for n, d in _neighbours(conn, change.enodeb_name) if n not in names and _status(conn, n, now) != "DOWN"]
            for other, weight in _weights(live).items():
                spill[other] = spill.get(other, 0.0) + shed * weight

    receivers: list[LoadPrediction] = []
    for other, extra in sorted(spill.items()):
        current = _current_prb(conn, other, now)
        predicted = round(min(100.0, current + extra), 1) if current is not None else None
        receivers.append(
            LoadPrediction(
                enodeb_name=other,
                status=_status(conn, other, now),
                distance_km=None,
                current_prb=current,
                predicted_prb=predicted,
                change_points=round(predicted - current, 1) if predicted is not None and current is not None else None,
                overloaded=predicted is not None and predicted >= network_model.OVERLOAD_PRB,
            )
        )
        if predicted is not None and predicted >= network_model.OVERLOAD_PRB:
            reasons.append(f"{other}: would overload at {predicted:g}% PRB after absorbing shed traffic")
    if any(t.status == "DOWN" for t in tilted):
        reasons.append("A tilted tower is DOWN; tilting it changes nothing")

    def build(sim_id: str) -> TiltSimulation:
        return TiltSimulation(
            sim_id=sim_id,
            changes=parsed,
            tilted=tilted,
            coverage_loss_pct=coverage,
            receivers=receivers,
            recommended=not reasons,
            reasons=reasons or ["Predicted loads are within limits and coverage loss is acceptable"],
        )

    sim_id = _store(conn, "tilt", {"changes": [c.model_dump() for c in parsed], "now_min": now}, build)
    return wrap(
        conn,
        source=SOURCE,
        tool="twin_simulate_tilt",
        data=_result(conn, sim_id, TiltSimulation),
        ref=sim_id,
    )


# ---------- stored simulations ----------


def _result[M: (FailureSimulation, TiltSimulation)](conn: sqlite3.Connection, sim_id: str, model: type[M]) -> M:
    row = conn.execute("SELECT result FROM twin_simulation WHERE sim_id = ?", (sim_id,)).fetchone()
    return model.model_validate(json.loads(row["result"]))


def get_simulation(conn: sqlite3.Connection, simulation_id: str) -> Envelope[SimulationRecord]:
    sid = parse_simulation_id(simulation_id)
    row: sqlite3.Row | None = conn.execute("SELECT * FROM twin_simulation WHERE sim_id = ?", (sid,)).fetchone()
    if row is None:
        raise NotFoundError(f"Simulation {sid} not found")
    record = SimulationRecord(
        sim_id=sid,
        kind=row["kind"],
        at=row["at"],
        params=json.loads(row["params"]),
        result=json.loads(row["result"]),
    )
    return wrap(conn, source=SOURCE, tool="twin_get_simulation", data=record, ref=sid)