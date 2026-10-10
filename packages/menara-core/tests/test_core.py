from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from menara_core import clock, privacy
from menara_core.audit import append_audit
from menara_core.db import connect
from menara_core.envelope import wrap
from menara_core.errors import DatabaseNotSeededError, InvalidInputError, TokenError
from menara_core.ids import (
    enodeb_of_cell,
    parse_cell_id,
    parse_enodeb,
    parse_ticket_id,
    site_id_for,
)
from menara_core.scenario import load_scenario
from menara_core.seed.build import build
from menara_core.settings import default_scenario_path
from menara_core.testing import build_test_db
from menara_core.tokens import issue_token, verify_token

KEY = b"test-key"


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("core-db"))


def test_id_parsers() -> None:
    assert parse_enodeb(" KKRI-0142 ") == "KKRI-0142"
    assert site_id_for("KKRI-0142") == "SITE-KKRI-0142"
    assert enodeb_of_cell(parse_cell_id("KKRI-0142-B1")) == "KKRI-0142"
    assert parse_ticket_id("TK-88213") == "TK-88213"
    for bad in ("kkri-0142", "KKRI0142", "KKRI-142"):
        with pytest.raises(InvalidInputError):
            parse_enodeb(bad)


def test_msisdn_hash_is_stable_salted_and_never_the_number() -> None:
    first = privacy.hash_msisdn("+60 12-345 6789", salt="a")
    assert first == privacy.hash_msisdn("0123456789".replace("0", "60", 1), salt="a")
    assert first != privacy.hash_msisdn("+60 12-345 6789", salt="b")
    assert len(first) == 16 and "123456789" not in first


def test_small_aggregates_are_suppressed() -> None:
    assert privacy.suppress_small(4) is None
    assert privacy.suppress_small(5) == 5
    assert privacy.coarsen_location(5.53104, 102.19697) == (5.531, 102.197)


def test_token_roundtrip_and_failure_modes() -> None:
    token = issue_token(KEY, action="tilt_cells", target="KKRI-0143", approved_by="human:izzham", now=1000)
    assert verify_token(KEY, token, action="tilt_cells", target="KKRI-0143", now=1100).approved_by == "human:izzham"
    with pytest.raises(TokenError, match="expired"):
        verify_token(KEY, token, action="tilt_cells", target="KKRI-0143", now=1301)
    with pytest.raises(TokenError, match="different"):
        verify_token(KEY, token, action="reset_cell", target="KKRI-0143", now=1100)
    with pytest.raises(TokenError, match="signature"):
        verify_token(b"other-key", token, action="tilt_cells", target="KKRI-0143", now=1100)
    with pytest.raises(TokenError, match="signature"):
        payload, sig = token.split(".")
        verify_token(KEY, f"{payload[:-2]}AA.{sig}", action="tilt_cells", target="KKRI-0143", now=1100)
    with pytest.raises(TokenError, match="Malformed"):
        verify_token(KEY, "nodot", action="a", target="b")


def test_seed_is_deterministic(tmp_path: Path) -> None:
    scenario = load_scenario(default_scenario_path())
    first, second = tmp_path / "a.db", tmp_path / "b.db"
    build(first, scenario, towers=30, seed=11)
    build(second, scenario, towers=30, seed=11)
    query = "SELECT * FROM tower ORDER BY enodeb_name"
    kpi = "SELECT * FROM tower_kpi ORDER BY enodeb_name, t_min"
    with sqlite3.connect(first) as a, sqlite3.connect(second) as b:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()
        assert a.execute(kpi).fetchall() == b.execute(kpi).fetchall()


def test_seed_contains_scripted_cluster_and_national_spread(db_file: Path) -> None:
    conn = connect(db_file)
    assert conn.execute("SELECT COUNT(*) FROM tower WHERE enodeb_name LIKE 'KKRI-%'").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(DISTINCT state) FROM tower").fetchone()[0] >= 10
    nearest = [r[0] for r in conn.execute(
        "SELECT neighbour_name FROM tower_neighbour WHERE enodeb_name='KKRI-0142' ORDER BY distance_km LIMIT 2"
    )]
    assert nearest == ["KKRI-0143", "KKRI-0144"]
    assert conn.execute("SELECT value FROM seed_meta WHERE key='synthetic'").fetchone()[0] == "true"


def test_clock_and_envelope(db_file: Path) -> None:
    conn = connect(db_file)
    assert clock.now_min(conn) == 0
    assert clock.as_of(conn).startswith("2026-11-14T07:00:00")
    env = wrap(conn, source="x-mcp", tool="x_tool", data={"a": 1}, ref="R", confidence=0.9)
    assert env.synthetic is True and env.evidence[0].confidence == 0.9
    assert env.model_dump(mode="json")["synthetic"] is True


def test_connections_are_read_only_unless_table_is_owned(db_file: Path) -> None:
    reader = connect(db_file)
    with pytest.raises(sqlite3.OperationalError):
        reader.execute("DELETE FROM tower")
    owner = connect(db_file, owned_tables={"audit_log"})
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        owner.execute("DELETE FROM tower")
    with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
        owner.execute("DROP TABLE tower")
    append_audit(owner, actor="policy-mcp", action="tilt_cells", target="KKRI-0143", decision="allow", detail={"n": 1})
    assert owner.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] >= 1
    owner.execute("DELETE FROM audit_log")
    owner.commit()


def test_missing_database_has_a_helpful_error(tmp_path: Path) -> None:
    with pytest.raises(DatabaseNotSeededError, match="menara-seed"):
        connect(tmp_path / "nope.db")
