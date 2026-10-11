"""Synthetic customer-care data: notice templates in four languages and the language mix per state."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db

LANGUAGES = {"ms", "en", "zh", "ta"}
KINDS = {"OUTAGE", "RESTORED", "DEGRADED"}


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("care"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_there_is_a_template_for_every_kind_and_language(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT kind, language FROM care_template").fetchall()
    assert {(r["kind"], r["language"]) for r in rows} == {(k, lang) for k in KINDS for lang in LANGUAGES}


def test_templates_use_the_placeholders_and_carry_no_real_number_or_brand(conn: sqlite3.Connection) -> None:
    for row in conn.execute("SELECT * FROM care_template"):
        body = row["body"]
        assert "{area}" in body and "{care_line}" in body
        assert not re.search(r"\d{5,}", body) and not re.search(r"\+?60\d", body)
        assert "telekom" not in body.lower() and "unifi" not in body.lower()
    outage = conn.execute("SELECT body FROM care_template WHERE kind = 'OUTAGE' AND language = 'en'").fetchone()["body"]
    assert "{cause}" in outage and "{eta}" in outage


def test_every_state_has_a_language_mix_that_sums_to_one(conn: sqlite3.Connection) -> None:
    states = {r["state"] for r in conn.execute("SELECT DISTINCT state FROM tower")}
    sums = {r["state"]: r["total"] for r in conn.execute("SELECT state, SUM(share) AS total FROM care_language_mix GROUP BY state")}
    assert states <= set(sums) and all(abs(v - 1.0) < 1e-6 for v in sums.values())
    languages = {r["language"] for r in conn.execute("SELECT DISTINCT language FROM care_language_mix")}
    assert languages == LANGUAGES


def test_malay_leads_in_the_east_coast_and_chinese_is_strong_in_penang(conn: sqlite3.Connection) -> None:
    def share(state: str, language: str) -> float:
        return float(conn.execute("SELECT share FROM care_language_mix WHERE state = ? AND language = ?", (state, language)).fetchone()[0])

    assert share("Kelantan", "ms") > 0.7
    assert share("Pulau Pinang", "zh") > share("Kelantan", "zh") * 3


def test_the_notice_table_starts_empty(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT COUNT(*) FROM care_notice").fetchone()[0] == 0