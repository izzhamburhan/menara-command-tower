"""Typed contracts for sensors-mcp responses (the `data` field of the envelope). Fictional sensors, invented readings."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

NOTE = "Synthetic: fictional sensors and invented readings for a demo."
Status = Literal["OK", "WARNING", "DANGER"]


class Centre(BaseModel):
    lat: float
    lng: float


class SensorView(BaseModel):
    sensor_id: str
    kind: str
    name: str
    owner: str
    town: str
    enodeb_name: str
    lat: float
    lng: float
    unit: str
    value: float
    at: str
    status: Status
    distance_km: float


class SensorList(BaseModel):
    center: Centre
    radius_km: float
    sensors: list[SensorView]
    returned: int
    note: str = NOTE


class ReadingPoint(BaseModel):
    t_min: int
    at: str
    value: float


class Readings(BaseModel):
    sensor_id: str
    kind: str
    name: str
    unit: str
    window_min: int
    points: list[ReadingPoint]
    latest: float
    min_value: float
    max_value: float
    note: str = NOTE


class Alert(BaseModel):
    sensor_id: str
    kind: str
    name: str
    owner: str
    town: str
    unit: str
    value: float
    warn_value: float
    danger_value: float
    status: Status
    trend_per_hour: float
    projected_min_to_danger: int | None
    distance_km: float


class AlertList(BaseModel):
    center: Centre
    radius_km: float
    alerts: list[Alert]
    returned: int
    note: str = NOTE
