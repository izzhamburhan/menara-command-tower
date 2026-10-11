"""Typed contracts for field-mcp responses (the `data` field of the envelope). Fictional crew; all numbers are synthetic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NOTE = "Synthetic: fictional technicians and invented parts, speeds and times for a demo."
Access = Literal["ROAD", "BOAT"]
JobStatus = Literal["EN_ROUTE", "ON_SITE", "DONE"]


class PartStock(BaseModel):
    part: str
    qty: int


class Candidate(BaseModel):
    tech_id: str
    name: str
    depot_id: str
    skills: list[str]
    distance_km: float
    eta_min: int
    access: Access
    parts: list[PartStock]


class Crew(BaseModel):
    enodeb_name: str
    skill: str
    access: Access
    flood_depth_m: float
    road_safe: bool
    safe_to_dispatch: bool
    safety_note: str
    candidates: list[Candidate]
    note: str = NOTE


class Job(BaseModel):
    job_id: str
    tech_id: str
    tech_name: str
    enodeb_name: str
    task: str
    skill: str
    dispatched_at: str
    eta_min: int
    access: Access
    approved_by: str
    status: JobStatus
    eta_left_min: int
    note: str = NOTE


class JobList(BaseModel):
    jobs: list[Job]
    returned: int
