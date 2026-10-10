"""Scenario file model. The scripted timeline (t_min = minutes since T0) drives the seeded data."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Status = Literal["UP", "DEGRADED", "DOWN"]
Severity = Literal["CRITICAL", "MAJOR", "MINOR", "WARNING"]


class ClusterTower(BaseModel):
    enodeb: str
    lat: float
    lng: float


class Cluster(BaseModel):
    code: str
    town: str
    state: str
    towers: list[ClusterTower]


class BaselineKpi(BaseModel):
    prb_util: float
    drop_rate: float
    throughput_mbps: float


class StateEvent(BaseModel):
    t_min: int
    tower: str
    status: Status
    battery_pct: int = Field(ge=0, le=100)
    mains_ok: bool


class AlarmEvent(BaseModel):
    id: str
    tower: str
    code: str
    severity: Severity
    message: str
    raised_min: int
    cleared_min: int | None = None


class KpiProfile(BaseModel):
    tower: str
    from_min: int
    prb_util: float
    drop_rate: float
    throughput_mbps: float


class TicketStorm(BaseModel):
    hub: str
    first_id: int
    count: int = Field(ge=1)
    window_min: int = Field(ge=1)
    max_distance_km: float
    subscribers_per_tower: int = Field(ge=1)
    hub_share: float = Field(ge=0, le=1)
    first_summary: str
    localities: list[str]
    summaries: list[str]


class Station(BaseModel):
    id: str
    name: str
    lat: float
    lng: float


class RainStep(BaseModel):
    from_min: int
    mm: float
    lightning: int


class WeatherScenario(BaseModel):
    station: Station
    rain_profile: list[RainStep]


class FeederSpec(BaseModel):
    id: str
    name: str
    customers: int
    towers: list[str]


class FeederEvent(BaseModel):
    t_min: int
    feeder: str
    status: Literal["ENERGISED", "AT_RISK", "TRIPPED"]
    note: str
    restoration_eta_min: int | None = None


class GridScenario(BaseModel):
    feeders: list[FeederSpec]
    events: list[FeederEvent]


class GaugeSpec(BaseModel):
    id: str
    river: str
    station: str
    lat: float
    lng: float
    warning_m: float
    danger_m: float


class LevelPoint(BaseModel):
    t_min: int
    m: float


class ExtentStep(BaseModel):
    id: str
    from_min: int
    name: str
    lat: float
    lng: float
    radius_km: float
    max_depth_m: float


class FloodScenario(BaseModel):
    gauge: GaugeSpec
    levels: list[LevelPoint]
    extents: list[ExtentStep]


SiteKind = Literal["HOSPITAL", "CLINIC", "POLICE", "FIRE", "SCHOOL", "ENTERPRISE"]


class SiteSpec(BaseModel):
    id: str
    name: str
    kind: SiteKind
    lat: float
    lng: float
    serving: str


class PolicyDefaults(BaseModel):
    auto_allow_max_subscribers: int
    auto_allow_min_confidence: float
    peak_start_hour: int
    peak_end_hour: int
    max_actions_per_hour: int
    token_ttl_s: int


class ScriptedFailure(BaseModel):
    action: str
    tower: str
    attempt: int
    efficacy: float


class RanScenario(BaseModel):
    scripted_failures: list[ScriptedFailure]


class RoadFinding(BaseModel):
    status: str
    water_depth_m: float
    passable_by: str


class GensetFinding(BaseModel):
    status: str
    access: str


class DroneFinding(BaseModel):
    access_road: RoadFinding
    tower_structure: str
    antenna_alignment: str
    power_cabinet: str
    genset: GensetFinding
    hazards: list[str]
    summary: str
    confidence: float


class Depot(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    drones: list[str]


class DroneScenario(BaseModel):
    speed_kmh: float
    inspect_min: int
    depots: list[Depot]
    findings: dict[str, DroneFinding]


class Scenario(BaseModel):
    name: str
    start: str
    default_now_min: int = 0
    cluster: Cluster
    baseline_kpi: BaselineKpi
    state_events: list[StateEvent]
    alarm_events: list[AlarmEvent]
    kpi_profiles: list[KpiProfile]
    tickets: TicketStorm
    weather: WeatherScenario
    grid: GridScenario
    flood: FloodScenario
    sites: list[SiteSpec]
    subscribers_est: dict[str, int]
    policy: PolicyDefaults
    ran: RanScenario
    drone: DroneScenario


def load_scenario(path: Path) -> Scenario:
    with path.open(encoding="utf-8") as handle:
        return Scenario.model_validate(yaml.safe_load(handle))
