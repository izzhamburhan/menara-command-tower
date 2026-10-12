"""Typed contracts for ticket-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from pydantic import BaseModel


class Note(BaseModel):
    note_id: int
    at: str
    author: str
    text: str


class TicketDetail(BaseModel):
    ticket_id: str
    created_at: str
    service: str
    category: str
    status: str
    location_text: str
    lat: float | None
    lng: float | None
    customer_ref: str
    summary: str
    language: str
    resolved_at: str | None
    notes: list[Note]


class ClusterTicket(BaseModel):
    ticket_id: str
    created_at: str
    category: str
    status: str
    location_text: str
    lat: float
    lng: float
    distance_km: float


class LocationCount(BaseModel):
    location_text: str
    count: int


class Centroid(BaseModel):
    lat: float
    lng: float


class TicketCluster(BaseModel):
    anchor_ticket: str
    radius_km: float
    window_min: int
    count: int
    span_min: int
    centroid: Centroid | None
    top_locations: list[LocationCount]
    tickets: list[ClusterTicket]
    returned: int
    truncated: bool


class Resolution(BaseModel):
    resolved: list[str]
    already_resolved: list[str]
    count: int
    resolved_by: str


class NoteAdded(BaseModel):
    ticket_id: str
    note: Note


class NttSummary(BaseModel):
    ntt_id: str
    created_at: str
    network_element_id: str
    fault_type: str
    severity: str
    status: str
    summary: str
    ctt_count: int


class McmcEligibility(BaseModel):
    can_send: bool
    can_send_display_message: str
    outage_duration_min: int
    is_mcmc_closure_sent: bool
    is_mcmc_comprehensive_required: bool
    comprehensive_report_aging_days: int | None
    reasons: list[str]


class NttDetail(BaseModel):
    ntt_id: str
    created_at: str
    network_element_id: str
    fault_type: str
    severity: str
    status: str
    summary: str
    ctt_count: int
    linked_ctt_ids: list[str]
    notes: list[Note]
    resolved_at: str | None
    resolved_by: str | None
    resolution_note: str | None
    mcmc_closure_sent: bool
    mcmc_comprehensive_required: bool


class NttList(BaseModel):
    ntts: list[NttSummary]
    total: int
    truncated: bool


class NttLinkResult(BaseModel):
    ntt_id: str
    linked: list[str]
    already_linked: list[str]
    ctt_count: int


class NttUnlinkResult(BaseModel):
    ntt_id: str
    unlinked_ticket_id: str
    ctt_count: int


class NttResolution(BaseModel):
    ntt_id: str
    status: str
    resolved_ctts: list[str]
    resolution_note: str
    resolved_by: str
    mcmc: McmcEligibility
