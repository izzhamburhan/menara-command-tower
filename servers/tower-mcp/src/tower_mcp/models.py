"""Typed contracts for tower-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TowerStatus = Literal["UP", "DEGRADED", "DOWN", "UNKNOWN"]
Severity = Literal["CRITICAL", "MAJOR", "MINOR", "WARNING"]


class KpiPoint(BaseModel):
    t_min: int | None  # scenario minutes; None from a live source
    at: str
    prb_util: float
    drop_rate: float
    throughput_mbps: float


class NeighbourInfo(BaseModel):
    enodeb_name: str
    distance_km: float
    status: TowerStatus
    prb_util: float | None


class Alarm(BaseModel):
    alarm_id: str
    enodeb_name: str
    code: str
    severity: Severity
    message: str
    raised_at: str
    cleared_at: str | None
    active: bool


class TowerDetail(BaseModel):
    enodeb_name: str
    site_id: str
    name: str
    town: str
    state: str
    lat: float
    lng: float
    tower_type: str
    vendor: str
    firmware: str
    status: TowerStatus
    battery_pct: int | None
    mains_ok: bool | None
    cells: list[str]
    active_alarm_count: int
    latest_kpi: KpiPoint | None
    neighbours: list[NeighbourInfo]


class TowerPin(BaseModel):
    enodeb_name: str
    site_id: str
    town: str
    state: str
    lat: float
    lng: float
    status: TowerStatus


class TowerList(BaseModel):
    towers: list[TowerPin]
    returned: int
    truncated: bool


class KpiSummary(BaseModel):
    samples: int
    avg_prb_util: float | None
    max_prb_util: float | None
    max_drop_rate: float | None
    min_throughput_mbps: float | None


class KpiWindow(BaseModel):
    enodeb_name: str
    window_min: int
    points: list[KpiPoint]
    summary: KpiSummary


class AlarmList(BaseModel):
    alarms: list[Alarm]
    returned: int
    truncated: bool
