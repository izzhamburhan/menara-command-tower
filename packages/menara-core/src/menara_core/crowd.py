"""The crowd model shared by events-mcp and exposure-mcp: how a crowd loads the towers around a venue.

A crowd of N people adds `N x PRB_POINTS_PER_ATTENDEE` PRB points in total, spread over the nearest towers by inverse
distance (the closest takes the most). A tower's baseline is its average PRB. Invented numbers, for a demo.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any, Literal

from menara_core.geo import haversine_km

SERVING_TOWERS = 5
PRB_POINTS_PER_ATTENDEE = 0.004
DISTANCE_FLOOR_KM = 0.5
MEDIUM_PRB, HIGH_PRB = 70.0, 85.0
Risk = Literal["LOW", "MEDIUM", "HIGH"]


def serving_towers(conn: sqlite3.Connection, lat: float, lng: float, count: int = SERVING_TOWERS) -> list[tuple[str, float]]:
    """The nearest towers to a point as (enodeb_name, distance_km), nearest first."""
    ranked = sorted(
        ((haversine_km(lat, lng, r["lat"], r["lng"]), r["enodeb_name"]) for r in conn.execute("SELECT enodeb_name, lat, lng FROM tower")),
    )
    return [(name, round(distance, 3)) for distance, name in ranked[:count]]


def uplift_by_tower(conn: sqlite3.Connection, event: Mapping[str, Any] | sqlite3.Row) -> dict[str, float]:
    """PRB points a crowd adds to each serving tower. The shares sum to attendance x PRB_POINTS_PER_ATTENDEE."""
    towers = serving_towers(conn, event["lat"], event["lng"])
    weights = {name: 1.0 / (distance + DISTANCE_FLOOR_KM) for name, distance in towers}
    total_weight = sum(weights.values())
    total = event["attendance"] * PRB_POINTS_PER_ATTENDEE
    return {name: total * weight / total_weight for name, weight in weights.items()}


def baseline_prb(conn: sqlite3.Connection, enodeb_name: str) -> float:
    row = conn.execute("SELECT AVG(prb_util) FROM tower_kpi WHERE enodeb_name = ?", (enodeb_name,)).fetchone()
    return round(float(row[0] or 0.0), 1)


def risk_for(prb: float) -> Risk:
    return "HIGH" if prb >= HIGH_PRB else "MEDIUM" if prb >= MEDIUM_PRB else "LOW"