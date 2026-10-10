"""Typed contracts for weather-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Intensity = Literal["NORMAL", "HEAVY", "VERY_HEAVY", "EXTREME"]
LightningActivity = Literal["NONE", "LOW", "HIGH", "SEVERE"]


class StationRef(BaseModel):
    station_id: str
    name: str
    lat: float
    lng: float
    distance_km: float


class RainPoint(BaseModel):
    t_min: int
    at: str
    rain_mm: float
    lightning_strikes: int


class Rainfall(BaseModel):
    station: StationRef
    window_min: int
    total_mm: float
    last_hour_mm: float
    peak_mm_per_hour: float
    rain_24h_mm: float
    intensity: Intensity
    points: list[RainPoint]


class Lightning(BaseModel):
    station: StationRef
    window_min: int
    total_strikes: int
    last_hour_strikes: int
    peak_strikes_per_hour: int
    activity: LightningActivity
