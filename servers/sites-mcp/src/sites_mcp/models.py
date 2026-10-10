"""Typed contracts for sites-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

SiteKind = Literal["HOSPITAL", "CLINIC", "POLICE", "FIRE", "SCHOOL", "ENTERPRISE"]


class Site(BaseModel):
    critical_site_id: str
    name: str
    kind: SiteKind
    state: str
    lat: float
    lng: float
    priority: int
    emergency_service: bool
    sla_customer: bool
    serving_enodeb: str


class SiteList(BaseModel):
    sites: list[Site]
    returned: int
    truncated: bool


class TowerSites(BaseModel):
    enodeb_name: str
    sites: list[Site]
    counts_by_kind: dict[str, int]
    emergency_sites: int
    sla_customers: int
