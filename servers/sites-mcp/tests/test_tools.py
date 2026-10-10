from __future__ import annotations

import sqlite3

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from sites_mcp import tools

KUALA_KRAI_BOX = (5.40, 102.10, 5.70, 102.30)


def test_clinic_is_an_emergency_service_site(conn: sqlite3.Connection) -> None:
    env = tools.get_site(conn, "CS-KKRI-01")
    assert env.synthetic is True
    site = env.data
    assert site.kind == "CLINIC" and site.emergency_service is True and site.priority == 1
    assert site.serving_enodeb == "KKRI-0142" and site.sla_customer is False
    assert "(synthetic)" in site.name
    assert env.evidence[0].tool == "sites_get_site"


def test_enterprise_customer_is_sla_but_not_emergency(conn: sqlite3.Connection) -> None:
    site = tools.get_site(conn, "CS-KKRI-06").data
    assert site.sla_customer is True and site.emergency_service is False and site.priority == 2


def test_schools_are_lowest_priority(conn: sqlite3.Connection) -> None:
    site = tools.get_site(conn, "CS-KKRI-04").data
    assert site.kind == "SCHOOL" and site.priority == 3 and site.emergency_service is False


def test_flooded_tower_serves_a_clinic_and_the_police(conn: sqlite3.Connection) -> None:
    data = tools.sites_for_tower(conn, "KKRI-0142").data
    assert {s.critical_site_id for s in data.sites} == {"CS-KKRI-01", "CS-KKRI-03"}
    assert data.counts_by_kind == {"CLINIC": 1, "POLICE": 1}
    assert data.emergency_sites == 2 and data.sla_customers == 0


def test_tower_with_no_sites_returns_an_empty_list(conn: sqlite3.Connection) -> None:
    data = tools.sites_for_tower(conn, "KKRI-0152").data
    assert data.sites == [] and data.emergency_sites == 0


def test_bbox_finds_the_scripted_sites_highest_priority_first(conn: sqlite3.Connection) -> None:
    data = tools.list_in_bbox(conn, *KUALA_KRAI_BOX).data
    assert {s.critical_site_id for s in data.sites} == {f"CS-KKRI-0{i}" for i in range(1, 7)}
    assert [s.priority for s in data.sites] == sorted(s.priority for s in data.sites)
    clinics = tools.list_in_bbox(conn, *KUALA_KRAI_BOX, kind="CLINIC").data
    assert [s.critical_site_id for s in clinics.sites] == ["CS-KKRI-01", "CS-KKRI-02"]


def test_every_site_is_served_by_a_real_tower(conn: sqlite3.Connection) -> None:
    orphans = conn.execute(
        "SELECT COUNT(*) FROM critical_site c LEFT JOIN tower t ON t.enodeb_name = c.serving_enodeb "
        "WHERE t.enodeb_name IS NULL"
    ).fetchone()[0]
    assert orphans == 0


def test_bbox_truncates(conn: sqlite3.Connection) -> None:
    data = tools.list_in_bbox(conn, 0.0, 95.0, 8.0, 120.0, limit=3).data
    assert data.returned == 3 and data.truncated is True


def test_validation_and_unknown_ids(conn: sqlite3.Connection) -> None:
    with pytest.raises(InvalidInputError):
        tools.get_site(conn, "SITE-KKRI-0142")
    with pytest.raises(NotFoundError):
        tools.get_site(conn, "CS-ZZZZ-99")
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(conn, 6.0, 100.0, 5.0, 101.0)
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(conn, *KUALA_KRAI_BOX, kind="MALL")
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(conn, *KUALA_KRAI_BOX, limit=0)
    with pytest.raises(NotFoundError):
        tools.sites_for_tower(conn, "ZZZZ-9999")
