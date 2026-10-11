"""scam-mcp tools: where scam calls and messages are spiking, and how many customers a shield would protect. Counts only."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from scam_mcp import tools

KUALA_KRAI = (5.531, 102.197)
KUALA_LUMPUR = (3.139, 101.687)


def test_hotspots_rank_patterns_by_reports_with_a_trend(conn: sqlite3.Connection) -> None:
    env = tools.get_hotspots(conn, *KUALA_KRAI, 30.0, 360)
    data = env.data
    assert env.synthetic is True and env.evidence[0].tool == "scam_get_hotspots"
    reports = [p.reports for p in data.patterns]
    assert reports == sorted(reports, reverse=True) and data.patterns and all(p.reports >= tools.MIN_REPORTS for p in data.patterns)
    assert all(p.trend in {"RISING", "STEADY", "FALLING"} and p.blocked >= 0 and p.severity in {"LOW", "MEDIUM", "HIGH"} for p in data.patterns)
    assert data.total_reports == sum(p.reports for p in data.patterns) + data.withheld_reports


def test_the_flood_relief_scam_leads_in_the_flood_region_and_is_rising(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    set_clock(-60)  # an hour before T0, as the surge builds
    data = tools.get_hotspots(conn, *KUALA_KRAI, 30.0, 360).data
    relief = next(p for p in data.patterns if "flood" in p.name.lower())
    assert relief.trend == "RISING" and relief.severity == "HIGH"
    far = tools.get_hotspots(conn, *KUALA_LUMPUR, 30.0, 360).data
    assert all("flood" not in p.name.lower() or p.reports < relief.reports for p in far.patterns)


def test_groups_under_5_reports_are_withheld(conn: sqlite3.Connection) -> None:
    data = tools.get_hotspots(conn, *KUALA_KRAI, 0.1, 60).data  # a tiny circle and an hour: almost nothing
    assert all(p.reports >= tools.MIN_REPORTS for p in data.patterns)
    assert data.withheld_patterns >= 0 and tools.MIN_REPORTS == 5
    assert data.total_reports == sum(p.reports for p in data.patterns) + data.withheld_reports


def test_an_empty_circle_gives_no_towns_and_a_warning(conn: sqlite3.Connection) -> None:
    env = tools.get_hotspots(conn, 0.0, 100.0, 1.0, 360)
    assert env.data.towns == [] and env.data.patterns == [] and env.warnings


def test_window_and_radius_are_validated(conn: sqlite3.Connection) -> None:
    for kwargs in ({"radius_km": 0.0}, {"radius_km": 101.0}, {"window_min": 59}, {"window_min": 1441}, {"lat": 91.0}, {"lng": 181.0}):
        args = {"lat": 5.5, "lng": 102.1, "radius_km": 10.0, "window_min": 360}
        args.update(kwargs)
        with pytest.raises(InvalidInputError):
            tools.get_hotspots(conn, **args)  # type: ignore[arg-type]


def test_pattern_lookup_and_unknown_pattern(conn: sqlite3.Connection) -> None:
    pid = conn.execute("SELECT pattern_id FROM scam_pattern ORDER BY pattern_id LIMIT 1").fetchone()[0]
    pattern = tools.get_pattern(conn, pid).data
    assert pattern.pattern_id == pid and pattern.example and pattern.advice and pattern.name.endswith("(synthetic)")
    with pytest.raises(NotFoundError):
        tools.get_pattern(conn, "SCM-99")


def test_protection_estimate_is_labelled_an_estimate_and_scales_with_the_circle(conn: sqlite3.Connection) -> None:
    small = tools.estimate_protection(conn, *KUALA_KRAI, 5.0).data
    large = tools.estimate_protection(conn, *KUALA_KRAI, 40.0).data
    assert "estimate" in small.note.lower() and small.customers_protected > 0 and small.loss_avoided_rm > 0
    assert large.customers_protected >= small.customers_protected and large.messages_blocked >= small.messages_blocked
    assert small.customers_protected == round(small.customers_in_area * tools.SHIELD_ADOPTION)
    assert small.loss_avoided_rm == round(small.messages_blocked * tools.SUCCESS_RATE * tools.AVG_LOSS_RM, 2)
    for kwargs in ({"radius_km": 0.0}, {"radius_km": 101.0}):
        with pytest.raises(InvalidInputError):
            tools.estimate_protection(conn, 5.5, 102.1, **kwargs)  # type: ignore[arg-type]


def test_no_response_contains_a_phone_number_or_a_person(conn: sqlite3.Connection) -> None:
    pid = conn.execute("SELECT pattern_id FROM scam_pattern LIMIT 1").fetchone()[0]
    for env in (
        tools.get_hotspots(conn, *KUALA_KRAI, 30.0, 360),
        tools.get_pattern(conn, pid),
        tools.estimate_protection(conn, *KUALA_KRAI, 30.0),
    ):
        text = json.dumps(env.model_dump(mode="json"))
        assert not re.search(r"\d{9,}", text) and "msisdn" not in text.lower() and "customer_ref" not in text.lower()
        assert env.synthetic is True and env.evidence
