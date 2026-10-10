"""tower-mcp tool logic. Plain functions over a TowerSource; server.py exposes them.

Nothing here knows whether the data is synthetic SQLite or a real API: that is the source's job.
"""

from __future__ import annotations

from menara_core.envelope import Envelope, wrap_at
from menara_core.errors import InvalidInputError, NotFoundError
from menara_core.ids import parse_enodeb

from tower_mcp.models import (
    AlarmList,
    KpiSummary,
    KpiWindow,
    NeighbourInfo,
    TowerDetail,
    TowerList,
)
from tower_mcp.source import TowerRecord, TowerSource

SOURCE = "tower-mcp"
MAX_LIMIT = 2000
MAX_WINDOW_MIN = 1440
STATUSES = {"UP", "DEGRADED", "DOWN", "UNKNOWN"}
SEVERITIES = {"CRITICAL", "MAJOR", "MINOR", "WARNING"}


def _require_tower(source: TowerSource, enodeb_name: str) -> TowerRecord:
    name = parse_enodeb(enodeb_name)
    tower = source.get_tower(name)
    if tower is None:
        raise NotFoundError(f"Tower {name} not found")
    return tower


def _wrap[T](
    source: TowerSource, tool: str, data: T, ref: str | None = None, warnings: list[str] | None = None
) -> Envelope[T]:
    return wrap_at(
        source.as_of(), source=SOURCE, tool=tool, data=data, ref=ref, warnings=warnings, synthetic=source.synthetic
    )


def get_status(source: TowerSource, enodeb_name: str) -> Envelope[TowerDetail]:
    tower = _require_tower(source, enodeb_name)
    name = tower.enodeb_name
    state = source.get_status(name)

    neighbours: list[NeighbourInfo] = []
    for n in source.get_neighbours(name):
        n_state = source.get_status(n.enodeb_name)
        n_kpi = source.latest_kpi(n.enodeb_name)
        neighbours.append(
            NeighbourInfo(
                enodeb_name=n.enodeb_name,
                distance_km=n.distance_km,
                status=n_state.status if n_state else "UNKNOWN",
                prb_util=n_kpi.prb_util if n_kpi else None,
            )
        )

    detail = TowerDetail(
        enodeb_name=name,
        site_id=tower.site_id,
        name=tower.name,
        town=tower.town,
        state=tower.state,
        lat=tower.lat,
        lng=tower.lng,
        tower_type=tower.tower_type,
        vendor=tower.vendor,
        firmware=tower.firmware,
        status=state.status if state else "UNKNOWN",
        battery_pct=state.battery_pct if state else None,
        mains_ok=state.mains_ok if state else None,
        cells=tower.cells,
        active_alarm_count=source.count_active_alarms(name),
        latest_kpi=source.latest_kpi(name),
        neighbours=neighbours,
    )
    return _wrap(source, "tower_get_status", detail, ref=name)


def list_in_bbox(
    source: TowerSource,
    min_lat: float,
    min_lng: float,
    max_lat: float,
    max_lng: float,
    status: str | None = None,
    limit: int = 500,
) -> Envelope[TowerList]:
    if not (-90 <= min_lat <= max_lat <= 90) or not (-180 <= min_lng <= max_lng <= 180):
        raise InvalidInputError("Invalid bbox: need -90<=min_lat<=max_lat<=90 and -180<=min_lng<=max_lng<=180")
    if status is not None and status not in STATUSES:
        raise InvalidInputError(f"status must be one of {sorted(STATUSES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    rows = source.list_towers(min_lat, min_lng, max_lat, max_lng, status, limit + 1)
    truncated = len(rows) > limit
    pins = rows[:limit]
    warnings = [f"Result truncated at {limit} towers; narrow the bbox or filter by status"] if truncated else []
    return _wrap(
        source,
        "tower_list_in_bbox",
        TowerList(towers=pins, returned=len(pins), truncated=truncated),
        warnings=warnings,
    )


def get_kpi(source: TowerSource, enodeb_name: str, window_min: int = 60) -> Envelope[KpiWindow]:
    tower = _require_tower(source, enodeb_name)
    if not 5 <= window_min <= MAX_WINDOW_MIN:
        raise InvalidInputError(f"window_min must be between 5 and {MAX_WINDOW_MIN}")
    points = source.kpi_window(tower.enodeb_name, window_min)
    summary = KpiSummary(
        samples=len(points),
        avg_prb_util=round(sum(p.prb_util for p in points) / len(points), 1) if points else None,
        max_prb_util=max((p.prb_util for p in points), default=None),
        max_drop_rate=max((p.drop_rate for p in points), default=None),
        min_throughput_mbps=min((p.throughput_mbps for p in points), default=None),
    )
    warnings = [] if points else ["No KPI samples in this window"]
    return _wrap(
        source,
        "tower_get_kpi",
        KpiWindow(enodeb_name=tower.enodeb_name, window_min=window_min, points=points, summary=summary),
        ref=tower.enodeb_name,
        warnings=warnings,
    )


def get_alarms(
    source: TowerSource,
    enodeb_name: str | None = None,
    severity: str | None = None,
    active_only: bool = True,
    limit: int = 200,
) -> Envelope[AlarmList]:
    if severity is not None and severity not in SEVERITIES:
        raise InvalidInputError(f"severity must be one of {sorted(SEVERITIES)}")
    if not 1 <= limit <= MAX_LIMIT:
        raise InvalidInputError(f"limit must be between 1 and {MAX_LIMIT}")
    name = _require_tower(source, enodeb_name).enodeb_name if enodeb_name else None
    rows = source.list_alarms(name, severity, active_only, limit + 1)
    truncated = len(rows) > limit
    alarms = rows[:limit]
    warnings = [f"Result truncated at {limit} alarms; filter by tower or severity"] if truncated else []
    return _wrap(
        source,
        "tower_get_alarms",
        AlarmList(alarms=alarms, returned=len(alarms), truncated=truncated),
        ref=name,
        warnings=warnings,
    )
