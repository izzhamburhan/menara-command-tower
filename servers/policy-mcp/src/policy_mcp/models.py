"""Typed contracts for policy-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Decision = Literal["allow", "ask", "deny"]
ApprovalStatus = Literal["PENDING", "AUTO_ALLOWED", "APPROVED", "REJECTED"]
Outcome = Literal["SUCCEEDED", "FAILED", "ROLLED_BACK"]


class RuleResult(BaseModel):
    rule: str
    on_fail: Literal["deny", "ask"]
    passed: bool
    detail: str


class PolicyDecision(BaseModel):
    action: str
    targets: list[str]
    decision: Decision
    reason: str
    rules: list[RuleResult]
    affected_subscribers: int
    touches_emergency: bool
    approval_id: str | None
    token: str | None
    token_expires_in_s: int | None


class Approval(BaseModel):
    approval_id: str
    action: str
    target: str
    status: ApprovalStatus
    confidence: float
    affected_subscribers: int
    touches_emergency: bool
    reason: str
    requested_at: str
    decided_by: str | None
    decided_at: str | None
    outcome: Outcome | None
    outcome_detail: str | None


class ApprovalList(BaseModel):
    approvals: list[Approval]
    returned: int


class TokenGrant(BaseModel):
    approval_id: str
    action: str
    target: str
    approved_by: str
    token: str
    token_expires_in_s: int


class PolicyStatus(BaseModel):
    kill_switch: bool
    settings: dict[str, str]
    peak_hour_now: bool
    actions_last_hour: int
    max_actions_per_hour: int
    pending_approvals: int
    known_actions: dict[str, str]


class KillSwitch(BaseModel):
    kill_switch: bool
    changed_by: str


class SettingChange(BaseModel):
    key: str
    value: str
    changed_by: str


class AuditEntry(BaseModel):
    id: int
    at: str
    actor: str
    action: str
    target: str
    decision: str
    detail: str


class AuditTrail(BaseModel):
    entries: list[AuditEntry]
    returned: int
