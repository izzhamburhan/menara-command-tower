"""Typed contracts for enterprise-mcp responses (the `data` field of the envelope). All numbers are synthetic."""

from __future__ import annotations

from pydantic import BaseModel

NOTE = "Synthetic estimate: fictional companies and invented values, rates and penalties for a demo."


class Centre(BaseModel):
    lat: float
    lng: float


class AtRisk(BaseModel):
    account_id: str
    name: str
    sector: str
    enodeb_name: str
    status: str
    outage_min: int
    monthly_value_rm: float
    revenue_per_hour_rm: float
    penalty_rm_per_hour: float
    penalty_accrued_rm: float
    projected_penalty_2h_rm: float
    credits_rm: float
    net_exposure_rm: float


class RevenueAtRisk(BaseModel):
    accounts: list[AtRisk]
    revenue_per_hour_rm: float
    penalty_accrued_rm: float
    projected_penalty_2h_rm: float
    credits_rm: float
    net_exposure_rm: float
    note: str = NOTE


class Account(BaseModel):
    account_id: str
    name: str
    sector: str
    enodeb_name: str
    status: str
    plan: str
    monthly_value_rm: float
    sla_availability_pct: float
    penalty_rm_per_hour: float
    distance_km: float


class AccountList(BaseModel):
    center: Centre
    radius_km: float
    accounts: list[Account]
    returned: int
    note: str = NOTE


class Credit(BaseModel):
    credit_id: str
    account_id: str
    from_min: int
    hours: float
    amount_rm: float
    issued_at: str
    approved_by: str
    note: str = NOTE
