from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core import kpi_overlay, network_model
from menara_core.db import connect
from menara_core.errors import InvalidInputError
from menara_core.ids import (
    parse_approval_id,
    parse_change_id,
    parse_drone_id,
    parse_incident_id,
    parse_mission_id,
    parse_simulation_id,
    target_key,
)
from menara_core.testing import build_test_db


def test_a_four_degree_downtilt_takes_91_to_63() -> None:
    assert network_model.predicted_prb(91.0, 4.0) == 63.0
    assert network_model.coverage_loss_pct(4.0) == 14.0


def test_the_load_reduction_is_capped_and_uptilt_adds_load() -> None:
    assert network_model.load_reduction(8.0) == network_model.MAX_LOAD_REDUCTION
    assert network_model.load_reduction(-8.0) == -network_model.MAX_LOAD_REDUCTION
    assert network_model.predicted_prb(80.0, -2.0) > 80.0
    assert network_model.predicted_prb(99.0, -6.0) == 100.0
    assert network_model.coverage_loss_pct(-3.0) == 0.0


def test_efficacy_scales_the_real_effect() -> None:
    full = network_model.effect_factors(4.0, 1.0)
    weak = network_model.effect_factors(4.0, 0.1)
    assert full[0] < weak[0] < 1.0 and full[2] > weak[2] > 1.0
    assert network_model.effect_factors(4.0, 0.0) == (1.0, 1.0, 1.0)
    assert round(91.0 * full[0], 1) == 63.0 and round(91.0 * weak[0], 1) == 88.2


@pytest.fixture
def writer(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    db = build_test_db(tmp_path)
    conn = connect(db, owned_tables={"ran_change", "ran_change_item", "ran_kpi_effect"})
    yield conn
    conn.close()


def _effect(conn: sqlite3.Connection, change_id: str, tower: str, from_min: int, factor: float, reverted: int | None = None) -> None:
    conn.execute(
        "INSERT INTO ran_change (change_id, action, status, applied_min, applied_at, reverted_min, approved_by, reason) "
        "VALUES (?, 'ran_tilt_cells', ?, ?, 'x', ?, 'human:t', '')",
        (change_id, "REVERTED" if reverted is not None else "ACTIVE", from_min, reverted),
    )
    conn.execute("INSERT INTO ran_kpi_effect VALUES (?, ?, ?, ?, ?, ?)", (change_id, tower, from_min, factor, 0.9, 1.1))
    conn.commit()


def test_without_changes_kpis_are_untouched(writer: sqlite3.Connection) -> None:
    assert kpi_overlay.adjust(writer, "KKRI-0143", 0, 91.0, 4.6, 22.0) == (91.0, 4.6, 22.0)


def test_an_effect_applies_only_from_its_start(writer: sqlite3.Connection) -> None:
    _effect(writer, "CHG-0001", "KKRI-0143", from_min=10, factor=0.7)
    assert kpi_overlay.adjust(writer, "KKRI-0143", 9, 100.0, 5.0, 20.0)[0] == 100.0
    assert kpi_overlay.adjust(writer, "KKRI-0143", 10, 100.0, 5.0, 20.0) == (70.0, 4.5, 22.0)
    assert kpi_overlay.adjust(writer, "KKRI-0144", 10, 100.0, 5.0, 20.0)[0] == 100.0  # another tower


def test_a_reverted_effect_stops_at_the_revert_time(writer: sqlite3.Connection) -> None:
    _effect(writer, "CHG-0001", "KKRI-0143", from_min=10, factor=0.7, reverted=30)
    assert kpi_overlay.adjust(writer, "KKRI-0143", 29, 100.0, 5.0, 20.0)[0] == 70.0
    assert kpi_overlay.adjust(writer, "KKRI-0143", 30, 100.0, 5.0, 20.0)[0] == 100.0


def test_active_effects_multiply_and_prb_is_capped_at_100(writer: sqlite3.Connection) -> None:
    _effect(writer, "CHG-0001", "KKRI-0143", from_min=0, factor=0.5)
    _effect(writer, "CHG-0002", "KKRI-0143", from_min=0, factor=0.5)
    assert kpi_overlay.adjust(writer, "KKRI-0143", 0, 80.0, 5.0, 20.0)[0] == 20.0
    _effect(writer, "CHG-0003", "KKRI-0144", from_min=0, factor=1.5)
    assert kpi_overlay.adjust(writer, "KKRI-0144", 0, 90.0, 5.0, 20.0)[0] == 100.0


def test_the_new_id_parsers_and_target_key() -> None:
    assert parse_approval_id("APR-0001") == "APR-0001"
    assert parse_change_id("CHG-0012") == "CHG-0012"
    assert parse_mission_id("MIS-0003") == "MIS-0003"
    assert parse_simulation_id("SIM-0004") == "SIM-0004"
    assert parse_incident_id("INC-0005") == "INC-0005"
    assert parse_drone_id("DRN-01") == "DRN-01"
    for parser, bad in (
        (parse_approval_id, "APR-1"),
        (parse_change_id, "chg-0001"),
        (parse_mission_id, "MIS0001"),
        (parse_simulation_id, "SIM-"),
        (parse_incident_id, "INC-12"),
        (parse_drone_id, "DRN-1"),
    ):
        with pytest.raises(InvalidInputError):
            parser(bad)
    assert target_key(["KKRI-0144", "KKRI-0143", "KKRI-0144"]) == "KKRI-0143,KKRI-0144"