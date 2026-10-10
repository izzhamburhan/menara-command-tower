"""The data-source interface for tower-mcp.

`tools.py` talks only to a `TowerSource`. Today's implementation reads the synthetic SQLite file
(`source_sqlite.py`); `source_http.py` reads a REST API that follows the contract in the README. Moving to
real data means writing a source (or a thin gateway in front of the real system), not touching the tools.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from pydantic import BaseModel

from tower_mcp.models import Alarm, KpiPoint, TowerPin, TowerStatus


class TowerRecord(BaseModel):
    """Static attributes of a tower and the ids of its cells."""

    enodeb_name: str
    site_id: str
    name: str
    town: str
    state: str
    lat: float
    lng: float
    tower_type: str
    vendor: str
    firmware: str
    cells: list[str]


class StatusRecord(BaseModel):
    status: TowerStatus
    battery_pct: int | None
    mains_ok: bool | None


class NeighbourRecord(BaseModel):
    enodeb_name: str
    distance_km: float


class TowerSource(Protocol):
    """Everything tower-mcp needs to know about towers. Methods return None or empty lists, never raise for missing data."""

    synthetic: bool
    """False only for real upstream data. It is copied into every response envelope."""

    def as_of(self) -> str:
        """ISO timestamp the data describes (scenario time, or now for a live source)."""
        ...

    def get_tower(self, enodeb_name: str) -> TowerRecord | None: ...

    def get_status(self, enodeb_name: str) -> StatusRecord | None: ...

    def get_neighbours(self, enodeb_name: str) -> list[NeighbourRecord]: ...

    def latest_kpi(self, enodeb_name: str) -> KpiPoint | None: ...

    def kpi_window(self, enodeb_name: str, window_min: int) -> list[KpiPoint]:
        """Samples from the last window_min minutes, oldest first."""
        ...

    def count_active_alarms(self, enodeb_name: str) -> int: ...

    def list_towers(
        self,
        min_lat: float,
        min_lng: float,
        max_lat: float,
        max_lng: float,
        status: str | None,
        limit: int,
    ) -> list[TowerPin]:
        """Towers in the box ordered by name, at most `limit` of them."""
        ...

    def list_alarms(
        self, enodeb_name: str | None, severity: str | None, active_only: bool, limit: int
    ) -> list[Alarm]:
        """Most severe first, at most `limit` of them."""
        ...


class SourceFactory(Protocol):
    """Opens a source for the duration of one tool call."""

    synthetic: bool

    def __call__(self) -> AbstractContextManager[TowerSource]: ...