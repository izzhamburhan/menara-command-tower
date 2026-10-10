"""Typed contracts for ran-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ChangeStatus = Literal["ACTIVE", "REVERTED", "COMPLETED"]


class CellConfig(BaseModel):
    cell_id: str
    band: str
    base_tilt_deg: float
    applied_delta_deg: float
    tilt_deg: float


class RanConfig(BaseModel):
    enodeb_name: str
    cells: list[CellConfig]
    active_changes: list[str]


class ChangeItem(BaseModel):
    enodeb_name: str
    cell_id: str
    tilt_delta_deg: float
    attempt: int


class Change(BaseModel):
    change_id: str
    action: str
    status: ChangeStatus
    applied_at: str
    reverted_at: str | None
    approved_by: str
    reason: str
    items: list[ChangeItem]
    towers: list[str]
    sandboxed: bool = True


class ChangeList(BaseModel):
    changes: list[Change]
    returned: int