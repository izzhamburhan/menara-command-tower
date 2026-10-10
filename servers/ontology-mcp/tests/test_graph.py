from __future__ import annotations

import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from ontology_mcp import tools


def test_blast_radius_of_the_flooded_tower(conn: sqlite3.Connection) -> None:
    env = tools.blast_radius(conn, "KKRI-0142")
    data = env.data
    assert env.synthetic is True
    assert data.origin.status == "DOWN" and data.origin.subscribers_est == 980
    assert data.towers_at_risk == 11
    assert data.subscribers_in_radius == 8420 and data.subscribers_at_risk == 7440
    assert data.counts_by_kind == {"CLINIC": 2, "POLICE": 1, "SCHOOL": 2, "ENTERPRISE": 1}
    assert data.emergency_sites == 3 and data.sla_customers == 1
    assert [t.distance_km for t in data.at_risk_towers] == sorted(t.distance_km for t in data.at_risk_towers)
    assert all(t.status == "UP" for t in data.at_risk_towers)
    assert env.evidence[0].tool == "ontology_blast_radius" and env.evidence[0].ref == "KKRI-0142"


def test_blast_radius_lists_feeders_tripped_first(conn: sqlite3.Connection) -> None:
    feeders = tools.blast_radius(conn, "KKRI-0142").data.feeders
    assert [(f.feeder_id, f.status, f.towers_in_radius) for f in feeders] == [
        ("FDR-KKRI-01", "TRIPPED", 1),
        ("FDR-KKRI-02", "AT_RISK", 3),
        ("FDR-KKRI-03", "ENERGISED", 8),
    ]


def test_sites_report_the_status_of_their_serving_tower(conn: sqlite3.Connection) -> None:
    sites = {s.critical_site_id: s for s in tools.blast_radius(conn, "KKRI-0142").data.critical_sites}
    assert sites["CS-KKRI-01"].serving_status == "DOWN"
    assert sites["CS-KKRI-02"].serving_status == "UP"
    assert [s.priority for s in sites.values()] == sorted(s.priority for s in sites.values())


def test_a_smaller_radius_shrinks_the_blast(conn: sqlite3.Connection) -> None:
    data = tools.blast_radius(conn, "KKRI-0142", radius_km=5).data
    assert [t.enodeb_name for t in data.at_risk_towers] == ["KKRI-0143", "KKRI-0144"]
    assert data.subscribers_in_radius == 980 + 820 + 790


def test_site_id_is_accepted_for_a_tower(conn: sqlite3.Connection) -> None:
    assert tools.blast_radius(conn, "SITE-KKRI-0142", radius_km=5).data.origin.enodeb_name == "KKRI-0142"


def test_blast_radius_truncates_lists_but_keeps_totals(conn: sqlite3.Connection) -> None:
    env = tools.blast_radius(conn, "KKRI-0142", limit=3)
    assert len(env.data.at_risk_towers) == 3 and env.data.towers_at_risk == 11
    assert env.data.truncated is True and env.warnings


def test_blast_radius_validation(conn: sqlite3.Connection) -> None:
    for kwargs in ({"radius_km": 0.5}, {"radius_km": 101.0}, {"limit": 0}):
        with pytest.raises(InvalidInputError):
            tools.blast_radius(conn, "KKRI-0142", **kwargs)  # type: ignore[arg-type]
    with pytest.raises(InvalidInputError):
        tools.blast_radius(conn, "nope")
    with pytest.raises(NotFoundError):
        tools.blast_radius(conn, "ZZZZ-9999")


def test_neighbours_include_the_overloaded_pair(conn: sqlite3.Connection) -> None:
    data = tools.neighbours(conn, "KKRI-0142").data
    by_name = {n.enodeb_name: n for n in data.neighbours}
    assert by_name["KKRI-0143"].prb_util == 91.0 and by_name["KKRI-0144"].prb_util == 91.0
    assert by_name["KKRI-0143"].nearest_of_origin is True
    assert [n.distance_km for n in data.neighbours] == sorted(n.distance_km for n in data.neighbours)
    assert all(n.nearest_of_origin or n.lists_origin for n in data.neighbours)


def test_upstream_of_the_flooded_tower(conn: sqlite3.Connection) -> None:
    data = tools.upstream_of(conn, "KKRI-0142").data
    feeder, gauge = data.dependencies
    assert feeder.kind == "POWER_FEEDER" and feeder.id == "FDR-KKRI-01" and feeder.status == "TRIPPED"
    assert gauge.kind == "FLOOD_GAUGE" and gauge.id == "GAUGE-KKRI-01" and gauge.status == "DANGER"
    assert data.shares_feeder_with == []


def test_upstream_shows_shared_fate_on_a_healthy_feeder(conn: sqlite3.Connection) -> None:
    data = tools.upstream_of(conn, "KKRI-0143").data
    assert data.dependencies[0].status == "ENERGISED"
    assert "KKRI-0144" in data.shares_feeder_with and "KKRI-0143" not in data.shares_feeder_with


def test_upstream_follows_the_clock(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-300)
    data = tools.upstream_of(conn, "KKRI-0142").data
    assert data.dependencies[0].status == "ENERGISED" and data.dependencies[1].status == "WARNING"
