"""Typed contracts for usage-mcp responses (the `data` field of the envelope). All numbers are synthetic estimates."""

from __future__ import annotations

from pydantic import BaseModel

NOTE = "Synthetic estimate: invented numbers for a demo, not real traffic and not about real people."


class Centre(BaseModel):
    lat: float
    lng: float


class AppUsage(BaseModel):
    rank: int
    app_id: str
    name: str
    category: str
    users_est: int
    reach_pct: float
    data_share_pct: float


class CategoryShare(BaseModel):
    category: str
    data_share_pct: float


class AreaUsage(BaseModel):
    center: Centre | None
    radius_km: float | None
    enodeb_name: str | None
    hour: int
    rank_by: str
    towers_counted: int
    total_users_est: int
    withheld: bool
    apps: list[AppUsage]
    categories: list[CategoryShare]
    busiest_hour: int | None
    note: str = NOTE


class TrendPoint(BaseModel):
    hour: int
    users_est: int
    reach_pct: float


class AppTrend(BaseModel):
    app_id: str
    name: str
    category: str
    center: Centre
    radius_km: float
    towers_counted: int
    total_users_est: int
    withheld: bool
    points: list[TrendPoint]
    peak_hour: int | None
    note: str = NOTE
