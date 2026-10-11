"""Typed contracts for care-mcp responses (the `data` field of the envelope). Counts only; all numbers are synthetic."""

from __future__ import annotations

from pydantic import BaseModel

NOTE = "Synthetic estimate: invented rates and wording for a demo. Counts only; no recipient list exists."


class CategoryCount(BaseModel):
    category: str
    count: int


class Impact(BaseModel):
    affected_towers: list[str]
    affected_customers: int
    withheld: bool
    cause: str | None
    open_tickets_nearby: int
    top_categories: list[CategoryCount]
    predicted_extra_tickets_if_silent: int
    predicted_extra_tickets_1h: int
    notified_customers: int
    notices_sent: int
    language_mix: dict[str, float]
    restoration_eta: str | None
    note: str = NOTE


class Draft(BaseModel):
    kind: str
    language: str
    message: str
    characters: int
    audience_towers: list[str]
    recipients_est: int
    channel: str
    cost_rm: float
    expected_deflection_pct: int
    restoration_eta: str | None
    note: str = NOTE


class Notice(BaseModel):
    notice_id: str
    kind: str
    towers: list[str]
    language: str
    recipients_est: int
    message: str
    sent_at: str
    approved_by: str
    tickets_deflected_est: int
    note: str = NOTE


class NoticeList(BaseModel):
    notices: list[Notice]
    returned: int
