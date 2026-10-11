"""Typed contracts for exposure-mcp responses (the `data` field of the envelope). All numbers are synthetic."""

from __future__ import annotations

from pydantic import BaseModel

NOTE = "Synthetic: invented products, prices and capacity for a demo; not a real offer."


class Profile(BaseModel):
    profile_id: str
    name: str
    description: str
    guaranteed: str
    headroom_prb: float
    price_rm_per_hour_per_tower: float


class ProfileList(BaseModel):
    profiles: list[Profile]
    note: str = NOTE


class TowerQuote(BaseModel):
    enodeb_name: str
    status: str
    current_prb: float
    event_uplift_prb: float
    reserved_prb: float
    headroom_available_prb: float
    feasible: bool
    reason: str


class Quote(BaseModel):
    profile_id: str
    duration_min: int
    start_in_min: int
    towers: list[TowerQuote]
    feasible_towers: list[str]
    all_feasible: bool
    price_rm: float
    reserved_prb_per_tower: float
    note: str = NOTE


class Booking(BaseModel):
    booking_id: str
    profile_id: str
    towers: list[str]
    customer: str
    from_min: int
    to_min: int
    price_rm: float
    approved_by: str
    note: str = NOTE
