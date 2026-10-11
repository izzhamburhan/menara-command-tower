"""Typed contracts for events-mcp responses (the `data` field of the envelope). Fictional events, invented numbers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

NOTE = "Synthetic: fictional events and invented crowd sizes and load figures for a demo."
Risk = Literal["LOW", "MEDIUM", "HIGH"]


class Centre(BaseModel):
    lat: float
    lng: float


class Event(BaseModel):
    event_id: str
    name: str
    kind: str
    town: str
    status: Literal["UPCOMING", "ONGOING"]
    starts_in_min: int
    duration_min: int
    attendance: int
    distance_km: float
    serving_towers: list[str]


class EventList(BaseModel):
    center: Centre
    radius_km: float
    within_min: int
    events: list[Event]
    returned: int
    note: str = NOTE


class TowerForecast(BaseModel):
    enodeb_name: str
    distance_km: float
    baseline_prb: float
    uplift_prb: float
    predicted_prb: float
    risk: Risk
    subscribers_est: int


class Forecast(BaseModel):
    event_id: str
    name: str
    kind: str
    attendance: int
    starts_in_min: int
    peak_in_min: int
    towers: list[TowerForecast]
    overall_risk: Risk
    subscribers_affected: int
    note: str = NOTE


class Recommendation(BaseModel):
    priority: Literal[1, 2, 3]
    towers: list[str]
    advice: str
    next_tool: str
    arguments: dict[str, Any]


class Plan(BaseModel):
    event_id: str
    name: str
    overall_risk: Risk
    recommendations: list[Recommendation]
    note: str = NOTE + " The plan is advice as data: nothing is executed."
