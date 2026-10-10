"""Typed contracts for flood-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

GaugeStatus = Literal["NORMAL", "WARNING", "DANGER"]
Trend = Literal["RISING", "FALLING", "STEADY"]


class Gauge(BaseModel):
    gauge_id: str
    river: str
    station: str
    state: str
    lat: float
    lng: float
    warning_m: float
    danger_m: float
    level_m: float | None
    status: GaugeStatus
    trend: Trend
    above_danger_by_m: float


class GaugePin(BaseModel):
    gauge_id: str
    river: str
    state: str
    lat: float
    lng: float
    level_m: float | None
    status: GaugeStatus


class GaugeList(BaseModel):
    gauges: list[GaugePin]
    returned: int
    truncated: bool


class PointCheck(BaseModel):
    lat: float
    lng: float
    inside_flood: bool
    extent_id: str | None
    extent_name: str | None
    depth_m: float | None
    distance_to_edge_km: float | None
    extent_radius_km: float | None
