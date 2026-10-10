"""Typed contracts for twin-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

TowerStatus = Literal["UP", "DEGRADED", "DOWN", "UNKNOWN"]


class TiltChange(BaseModel):
    enodeb_name: str
    tilt_delta_deg: float


class LoadPrediction(BaseModel):
    enodeb_name: str
    status: TowerStatus
    distance_km: float | None
    current_prb: float | None
    predicted_prb: float | None
    change_points: float | None
    overloaded: bool


class FailureSimulation(BaseModel):
    sim_id: str
    kind: Literal["failure"] = "failure"
    origin: str
    already_down: bool
    load_before_prb: float | None
    subscribers_impacted: int
    emergency_sites_affected: int
    critical_sites_affected: list[str]
    neighbours: list[LoadPrediction]
    overloaded_count: int
    subscribers_at_overload_risk: int
    recommendation: str


class TiltSimulation(BaseModel):
    sim_id: str
    kind: Literal["tilt"] = "tilt"
    changes: list[TiltChange]
    tilted: list[LoadPrediction]
    coverage_loss_pct: dict[str, float]
    receivers: list[LoadPrediction]
    recommended: bool
    reasons: list[str]


class SimulationRecord(BaseModel):
    sim_id: str
    kind: str
    at: str
    params: dict[str, Any]
    result: dict[str, Any]
