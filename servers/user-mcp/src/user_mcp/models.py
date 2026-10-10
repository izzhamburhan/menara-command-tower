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


class Centre(BaseModel):
    lat: float
    lng: float


class AreaSubscriber(BaseModel):
    msisdn_hash: str
    serving_cell: str
    enodeb_name: str
    cell_lat: float
    cell_lng: float
    attached: bool
    latest_label: ExperienceLabel | None


class TowerSubscribers(BaseModel):
    """subscribers_sampled counts the synthetic sample in this dataset; subscribers_est is the tower's population estimate."""

    enodeb_name: str
    cell_lat: float
    cell_lng: float
    subscribers_sampled: int
    subscribers_est: int | None


class SubscriberList(BaseModel):
    center: Centre | None
    radius_km: float | None
    enodeb_name: str | None
    towers: list[TowerSubscribers]
    subscribers: list[AreaSubscriber]
    subscribers_total: int | None
    returned: int
    truncated: bool
    withheld: bool
    location_precision: Literal["cell"] = "cell"


class TrailSegment(BaseModel):
    serving_cell: str
    enodeb_name: str
    cell_lat: float
    cell_lng: float
    arrived_at: str
    left_at: str | None
    duration_min: int
    current: bool


class Trail(BaseModel):
    msisdn_hash: str
    window_min: int
    segments: list[TrailSegment]
    moves: int
    distinct_towers: int
    location_precision: Literal["cell"] = "cell"
