"""Typed contracts for drone-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

MissionStatus = Literal["EN_ROUTE", "ON_SITE", "COMPLETE"]


class DroneInfo(BaseModel):
    drone_id: str
    depot_id: str
    depot_name: str
    status: Literal["IDLE", "ON_MISSION"]
    mission_id: str | None
    available_at: str | None


class DroneList(BaseModel):
    drones: list[DroneInfo]
    idle: int
    returned: int


class RoadFinding(BaseModel):
    status: str
    water_depth_m: float
    passable_by: str


class GensetFinding(BaseModel):
    status: str
    access: str


class Findings(BaseModel):
    """Canned vision output. Not produced by a real model."""

    vision_model: str = "synthetic-canned"
    access_road: RoadFinding
    tower_structure: str
    antenna_alignment: str
    power_cabinet: str
    genset: GensetFinding
    hazards: list[str]
    summary: str
    confidence: float


class Mission(BaseModel):
    mission_id: str
    drone_id: str
    depot_name: str
    enodeb_name: str
    status: MissionStatus
    progress_pct: int
    distance_km: float
    dispatched_at: str
    arrives_at: str
    completes_at: str
    approved_by: str
    reason: str
    findings: Findings | None


class MissionList(BaseModel):
    missions: list[Mission]
    returned: int
