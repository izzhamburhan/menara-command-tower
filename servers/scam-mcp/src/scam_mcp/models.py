"""Typed contracts for scam-mcp responses (the `data` field of the envelope). Counts only; all numbers are synthetic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NOTE = "Synthetic estimate: invented counts and rates for a demo. Counts only: no number, sender or person."
Trend = Literal["RISING", "STEADY", "FALLING"]


class Centre(BaseModel):
    lat: float
    lng: float


class Hotspot(BaseModel):
    pattern_id: str
    name: str
    kind: str
    severity: str
    reports: int
    blocked: int
    trend: Trend


class Hotspots(BaseModel):
    center: Centre
    radius_km: float
    window_min: int
    towns: list[str]
    patterns: list[Hotspot]
    total_reports: int
    withheld_patterns: int
    withheld_reports: int
    note: str = NOTE


class Pattern(BaseModel):
    pattern_id: str
    name: str
    kind: str
    severity: str
    example: str
    advice: str
    note: str = NOTE


class Protection(BaseModel):
    center: Centre
    radius_km: float
    customers_in_area: int
    customers_protected: int
    messages_blocked: int
    loss_avoided_rm: float
    window_hours: int
    note: str = NOTE + " The loss avoided is an estimate from a stated average."
