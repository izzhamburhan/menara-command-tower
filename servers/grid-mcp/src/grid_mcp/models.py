"""Typed contracts for grid-mcp responses (the `data` field of the envelope)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

FeederStatus = Literal["ENERGISED", "AT_RISK", "TRIPPED"]


class Feeder(BaseModel):
    feeder_id: str
    name: str
    state: str
    status: FeederStatus
    since: str | None
    note: str
    restoration_eta: str | None
    customers: int
    customers_affected: int


class TowerPower(BaseModel):
    enodeb_name: str
    feeder: Feeder
    mains_expected: bool


class FeederDetail(BaseModel):
    feeder: Feeder
    towers: list[str]


class OutageList(BaseModel):
    feeders: list[Feeder]
    returned: int
    customers_affected: int
