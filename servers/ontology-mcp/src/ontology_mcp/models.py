"""Typed contracts for ontology-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TowerStatus = Literal["UP", "DEGRADED", "DOWN", "UNKNOWN"]
Cause = Literal["FLOOD", "POWER", "TRANSPORT", "HARDWARE", "CONFIG", "UNKNOWN"]
IncidentStatus = Literal["OPEN", "MITIGATING", "RESOLVED"]


class TowerRef(BaseModel):
    enodeb_name: str
    site_id: str
    town: str
    state: str
    lat: float
    lng: float
    status: TowerStatus
    distance_km: float
    subscribers_est: int


class SiteRef(BaseModel):
    critical_site_id: str
    name: str
    kind: str
    priority: int
    emergency_service: bool
    sla_customer: bool
    serving_enodeb: str
    serving_status: TowerStatus


class FeederRef(BaseModel):
    feeder_id: str
    name: str
    status: str
    towers_in_radius: int


class BlastRadius(BaseModel):
    origin: TowerRef
    radius_km: float
    at_risk_towers: list[TowerRef]
    towers_at_risk: int
    subscribers_in_radius: int
    subscribers_at_risk: int
    critical_sites: list[SiteRef]
    counts_by_kind: dict[str, int]
    emergency_sites: int
    sla_customers: int
    feeders: list[FeederRef]
    truncated: bool


class NeighbourRef(BaseModel):
    enodeb_name: str
    distance_km: float
    status: TowerStatus
    prb_util: float | None
    nearest_of_origin: bool
    lists_origin: bool


class Neighbours(BaseModel):
    enodeb_name: str
    neighbours: list[NeighbourRef]


class Dependency(BaseModel):
    kind: Literal["POWER_FEEDER", "FLOOD_GAUGE"]
    id: str
    name: str
    status: str
    detail: str


class Upstream(BaseModel):
    enodeb_name: str
    dependencies: list[Dependency]
    shares_feeder_with: list[str]


class EvidenceRef(BaseModel):
    """Pointer to the MCP call that produced a claim. Mirrors the envelope's evidence entries."""

    source: str = Field(min_length=1, max_length=40)
    tool: str = Field(min_length=1, max_length=60)
    call_id: str = Field(min_length=1, max_length=40)
    ref: str | None = Field(default=None, max_length=60)


class IncidentNote(BaseModel):
    at: str
    text: str


class Incident(BaseModel):
    incident_id: str
    enodeb_name: str
    cause: Cause
    cause_confidence: float
    summary: str
    status: IncidentStatus
    created_at: str
    updated_at: str
    ticket_ids: list[str]
    evidence: list[EvidenceRef]
    notes: list[IncidentNote]


class IncidentList(BaseModel):
    incidents: list[Incident]
    returned: int