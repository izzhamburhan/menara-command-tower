from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from grid_mcp import tools
from menara_core.errors import InvalidInputError, NotFoundError


def test_flooded_tower_is_on_a_tripped_feeder(conn: sqlite3.Connection) -> None:
    env = tools.get_tower_power(conn, "KKRI-0142")
    assert env.synthetic is True
    feeder = env.data.feeder
    assert feeder.feeder_id == "FDR-KKRI-01" and feeder.status == "TRIPPED"
    assert feeder.since is not None and feeder.since.startswith("2026-11-14T03:00")
    assert feeder.customers_affected == 3200 == feeder.customers
    assert feeder.restoration_eta is None
    assert env.data.mains_expected is False
    assert env.evidence[0].tool == "grid_get_tower_power" and env.evidence[0].ref == "KKRI-0142"


def test_neighbouring_tower_has_power_and_riverside_tower_is_at_risk(conn: sqlite3.Connection) -> None:
    healthy = tools.get_tower_power(conn, "KKRI-0143").data
    assert healthy.feeder.status == "ENERGISED" and healthy.mains_expected is True
    assert healthy.feeder.customers_affected == 0 and healthy.feeder.since is None
    at_risk = tools.get_tower_power(conn, "KKRI-0148").data
    assert at_risk.feeder.status == "AT_RISK" and at_risk.mains_expected is True


def test_feeder_trip_happens_at_its_scripted_time(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    assert tools.get_tower_power(conn, "KKRI-0142").data.feeder.status == "ENERGISED"
    set_clock(-240)
    assert tools.get_tower_power(conn, "KKRI-0142").data.feeder.status == "TRIPPED"


def test_feeder_status_lists_its_towers(conn: sqlite3.Connection) -> None:
    detail = tools.get_feeder_status(conn, "FDR-KKRI-02").data
    assert detail.towers == ["KKRI-0148", "KKRI-0151", "KKRI-0153"]
    assert detail.feeder.status == "AT_RISK"


def test_outages_list_tripped_first(conn: sqlite3.Connection) -> None:
    data = tools.list_outages(conn).data
    assert [f.feeder_id for f in data.feeders] == ["FDR-KKRI-01", "FDR-KKRI-02"]
    assert data.customers_affected == 3200 and data.returned == 2


def test_outages_can_exclude_at_risk(conn: sqlite3.Connection) -> None:
    assert [f.feeder_id for f in tools.list_outages(conn, include_at_risk=False).data.feeders] == ["FDR-KKRI-01"]


def test_nothing_is_out_before_the_incident(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    assert tools.list_outages(conn).data.returned == 0


def test_every_tower_has_a_feeder(conn: sqlite3.Connection) -> None:
    orphans = conn.execute(
        "SELECT COUNT(*) FROM tower t LEFT JOIN grid_feeder_tower g ON g.enodeb_name = t.enodeb_name "
        "WHERE g.enodeb_name IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_validation_and_unknown_ids(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_tower_power(conn, "kkri0142")
    with pytest.raises(NotFoundError):
        tools.get_tower_power(conn, "ZZZZ-9999")
    with pytest.raises(InvalidInputError):
        tools.get_feeder_status(conn, "FDR-1")
    with pytest.raises(NotFoundError):
        tools.get_feeder_status(conn, "FDR-ZZZZ-99")
