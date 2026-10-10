"""TowerSource over a REST API that follows the "Tower API v1" contract in this server's README.

The contract is ours, not any real system's. A real OSS would sit behind a thin gateway or mapper that exposes
these endpoints. Responses from this source are marked `synthetic: false`.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from menara_core.errors import SourceUnavailableError
from pydantic import BaseModel, TypeAdapter, ValidationError

from tower_mcp.models import Alarm, KpiPoint, TowerPin
from tower_mcp.source import NeighbourRecord, StatusRecord, TowerRecord, TowerSource

DEFAULT_TIMEOUT_S = 10.0
LATEST_KPI_WINDOW_MIN = 60
ALARM_COUNT_LIMIT = 1000


class _Sample(BaseModel):
    at: str
    prb_util: float
    drop_rate: float
    throughput_mbps: float


class HttpTowerSource:
    synthetic = False

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def as_of(self) -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """JSON of a successful call, None for 404. Any other failure is SourceUnavailableError."""
        try:
            response = self._client.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        except httpx.HTTPError as exc:
            raise SourceUnavailableError(f"Tower API unreachable: {exc.__class__.__name__}") from exc
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise SourceUnavailableError(f"Tower API returned HTTP {response.status_code} for {path}")
        try:
            return response.json()
        except ValueError as exc:
            raise SourceUnavailableError(f"Tower API returned invalid JSON for {path}") from exc

    @staticmethod
    def _parse[M: BaseModel](model: type[M], payload: Any, path: str) -> M:
        try:
            return model.model_validate(payload)
        except ValidationError as exc:
            raise SourceUnavailableError(f"Tower API response for {path} does not match the contract") from exc

    @staticmethod
    def _parse_list[M: BaseModel](model: type[M], payload: Any, path: str) -> list[M]:
        try:
            return TypeAdapter(list[model]).validate_python(payload)  # type: ignore[valid-type]
        except ValidationError as exc:
            raise SourceUnavailableError(f"Tower API response for {path} does not match the contract") from exc

    def get_tower(self, enodeb_name: str) -> TowerRecord | None:
        path = f"/towers/{enodeb_name}"
        payload = self._get(path)
        return None if payload is None else self._parse(TowerRecord, payload, path)

    def get_status(self, enodeb_name: str) -> StatusRecord | None:
        path = f"/towers/{enodeb_name}/status"
        payload = self._get(path)
        return None if payload is None else self._parse(StatusRecord, payload, path)

    def get_neighbours(self, enodeb_name: str) -> list[NeighbourRecord]:
        path = f"/towers/{enodeb_name}/neighbours"
        return self._parse_list(NeighbourRecord, self._get(path) or [], path)

    def kpi_window(self, enodeb_name: str, window_min: int) -> list[KpiPoint]:
        path = f"/towers/{enodeb_name}/kpi"
        samples = self._parse_list(_Sample, self._get(path, {"window_min": window_min}) or [], path)
        return [
            KpiPoint(
                t_min=None,
                at=s.at,
                prb_util=s.prb_util,
                drop_rate=s.drop_rate,
                throughput_mbps=s.throughput_mbps,
            )
            for s in sorted(samples, key=lambda s: s.at)
        ]

    def latest_kpi(self, enodeb_name: str) -> KpiPoint | None:
        points = self.kpi_window(enodeb_name, LATEST_KPI_WINDOW_MIN)
        return points[-1] if points else None

    def count_active_alarms(self, enodeb_name: str) -> int:
        return len(self.list_alarms(enodeb_name, None, True, ALARM_COUNT_LIMIT))

    def list_towers(
        self, min_lat: float, min_lng: float, max_lat: float, max_lng: float, status: str | None, limit: int
    ) -> list[TowerPin]:
        params = {
            "min_lat": min_lat,
            "min_lng": min_lng,
            "max_lat": max_lat,
            "max_lng": max_lng,
            "status": status,
            "limit": limit,
        }
        return self._parse_list(TowerPin, self._get("/towers", params) or [], "/towers")

    def list_alarms(
        self, enodeb_name: str | None, severity: str | None, active_only: bool, limit: int
    ) -> list[Alarm]:
        params = {
            "enodeb_name": enodeb_name,
            "severity": severity,
            "active_only": "true" if active_only else "false",
            "limit": limit,
        }
        return self._parse_list(Alarm, self._get("/alarms", params) or [], "/alarms")


class HttpSourceFactory:
    """Opens a client for the tower API per tool call, or reuses an injected one (tests)."""

    synthetic = False

    def __init__(self, base_url: str, token: str | None = None, client: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client

    @contextmanager
    def __call__(self) -> Iterator[TowerSource]:
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        client = self._client or httpx.Client(base_url=self._base_url, headers=headers, timeout=DEFAULT_TIMEOUT_S)
        try:
            yield HttpTowerSource(client)
        finally:
            if self._client is None:
                client.close()
