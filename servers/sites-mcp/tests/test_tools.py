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
        tools.list_in_bbox(conn, *KUALA_KRAI_BOX, kind="ZOO")
    with pytest.raises(InvalidInputError):
        tools.list_in_bbox(conn, *KUALA_KRAI_BOX, limit=0)
    with pytest.raises(NotFoundError):
        tools.sites_for_tower(conn, "ZZZZ-9999")


WHOLE_COUNTRY = (0.0, 95.0, 8.0, 120.0)


def _a_mall(conn: sqlite3.Connection) -> str:
    return str(conn.execute("SELECT critical_site_id FROM critical_site WHERE kind = 'MALL' ORDER BY 1 LIMIT 1").fetchone()[0])


def test_a_mall_can_be_listed_by_kind(conn: sqlite3.Connection) -> None:
    data = tools.list_in_bbox(conn, *WHOLE_COUNTRY, kind="MALL").data
    assert data.sites and {s.kind for s in data.sites} == {"MALL"}
    assert {(s.priority, s.emergency_service, s.sla_customer) for s in data.sites} == {(4, False, False)}
    assert all("(synthetic)" in s.name for s in data.sites)


def test_get_site_returns_a_mall(conn: sqlite3.Connection) -> None:
    site = tools.get_site(conn, _a_mall(conn)).data
    assert site.kind == "MALL" and site.priority == 4 and site.emergency_service is False


def test_for_tower_counts_include_mall_when_the_tower_serves_one(conn: sqlite3.Connection) -> None:
    serving = conn.execute("SELECT serving_enodeb FROM critical_site WHERE kind = 'MALL' ORDER BY 1 LIMIT 1").fetchone()[0]
    data = tools.sites_for_tower(conn, serving).data
    assert data.counts_by_kind.get("MALL") == 1 and data.emergency_sites == sum(1 for s in data.sites if s.emergency_service)


def test_malls_come_after_every_other_kind_in_a_mixed_list(conn: sqlite3.Connection) -> None:
    kinds = [s.kind for s in tools.list_in_bbox(conn, *WHOLE_COUNTRY, limit=1000).data.sites]
    assert "MALL" in kinds and kinds[-1] == "MALL"
    assert kinds.index("MALL") > max(i for i, k in enumerate(kinds) if k != "MALL")