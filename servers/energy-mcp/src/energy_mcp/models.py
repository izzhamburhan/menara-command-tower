"""Typed contracts for energy-mcp responses (the `data` field of the envelope). All numbers are synthetic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NOTE = "Synthetic estimate: invented power, fuel and carbon figures for a demo, not real measurements."
Supply = Literal["MAINS", "BATTERY", "GENERATOR", "NONE"]


class Centre(BaseModel):
    lat: float
    lng: float


class TowerEnergy(BaseModel):
    enodeb_name: str
    status: str
    supply: Supply
    mains_ok: bool
    battery_pct: int
    load_pct: float
    base_kw: float
    draw_kw: float
    sleeping: bool
    active_action: str | None
    hours_left: float | None
    has_generator: bool
    generator_fuel_l: float
    generator_hours_left: float | None
    note: str = NOTE


class SleepCandidate(BaseModel):
    enodeb_name: str
    cells: int
    night_load_pct: float
    kwh_saved: float
    co2_kg_saved: float
    risk: Literal["LOW", "MEDIUM"]


class Savings(BaseModel):
    center: Centre
    radius_km: float
    hour: int
    window_open: bool
    window: str
    co2_kg_per_kwh: float
    candidates: list[SleepCandidate]
    total_kwh_saved: float
    total_co2_kg_saved: float
    note: str = NOTE


class SleepAction(BaseModel):
    action_id: str
    enodeb_name: str
    kind: str
    from_min: int
    to_min: int
    kwh_saved: float
    co2_kg_saved: float
    approved_by: str


class SleepResult(BaseModel):
    actions: list[SleepAction]
    total_kwh_saved: float
    total_co2_kg_saved: float
    note: str = NOTE
