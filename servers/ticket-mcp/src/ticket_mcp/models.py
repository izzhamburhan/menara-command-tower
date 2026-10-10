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
