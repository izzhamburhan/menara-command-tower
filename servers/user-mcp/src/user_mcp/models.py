"""Typed contracts for user-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ExperienceLabel = Literal["GOOD", "FAIR", "POOR", "NO_SERVICE"]


class ServingCell(BaseModel):
    msisdn_hash: str
    serving_cell: str
    enodeb_name: str
    attached: bool
    detached_since: str | None
    cell_lat: float
    cell_lng: float
    location_precision: Literal["cell"] = "cell"
    plan: str
    segment: str
    home_fibre: bool


class ExperiencePoint(BaseModel):
    t_min: int
    at: str
    score: float
    label: ExperienceLabel
    throughput_mbps: float
    drop_events: int
    rsrp_dbm: int


class ExperienceSummary(BaseModel):
    samples: int
    avg_score: float | None
    min_score: float | None
    worst_label: ExperienceLabel | None


class ExperienceWindow(BaseModel):
    msisdn_hash: str
    window_min: int
    latest: ExperiencePoint | None
    points: list[ExperiencePoint]
    summary: ExperienceSummary