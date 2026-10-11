"""Synthetic app usage: a catalogue, an hourly curve per app, and per-tower shares. Invented numbers, no per-person data."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import pytest
from menara_core.testing import build_test_db

EVENING = (20, 21)
NIGHT = 4


@pytest.fixture(scope="module")
def db_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_test_db(tmp_path_factory.mktemp("usage"))


@pytest.fixture
def conn(db_file: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_file)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()


def test_the_catalogue_has_14_apps_in_8_categories_and_real_names_without_logos(conn: sqlite3.Connection) -> None:
    apps = conn.execute("SELECT * FROM app ORDER BY app_id").fetchall()
    assert len(apps) == 14 and len({a["category"] for a in apps}) == 8
    names = {a["name"] for a in apps}
    assert {"TikTok", "Facebook", "Instagram", "Threads", "WhatsApp", "YouTube"} <= names
    assert {a["category"] for a in apps} == {
        "SHORT_VIDEO", "SOCIAL", "MESSAGING", "VIDEO_STREAMING", "MUSIC", "GAMING", "COMMERCE", "MOBILITY",
    }
    assert all("." not in a["app_id"] and a["app_id"] == a["app_id"].lower() for a in apps)


def test_every_tower_has_a_share_for_every_app(conn: sqlite3.Connection) -> None:
    towers = conn.execute("SELECT COUNT(*) FROM tower").fetchone()[0]
    assert conn.execute("SELECT COUNT(*) FROM tower_app_share").fetchone()[0] == towers * 14


def test_data_shares_of_a_tower_sum_to_one(conn: sqlite3.Connection) -> None:
    sums = conn.execute("SELECT SUM(data_share) AS s FROM tower_app_share GROUP BY enodeb_name").fetchall()
    assert sums and all(abs(r["s"] - 1.0) < 1e-6 for r in sums)


def test_user_shares_are_between_0_and_1(conn: sqlite3.Connection) -> None:
    low, high = conn.execute("SELECT MIN(user_share), MAX(user_share) FROM tower_app_share").fetchone()
    assert low > 0.0 and high <= 1.0


def test_hour_factors_exist_for_24_hours_and_evening_beats_the_small_hours_for_video_and_social(conn: sqlite3.Connection) -> None:
    assert conn.execute("SELECT COUNT(*) FROM app_hour_factor").fetchone()[0] == 14 * 24
    low, high = conn.execute("SELECT MIN(factor), MAX(factor) FROM app_hour_factor").fetchone()
    assert 0.0 < low < high <= 1.0
    rows = conn.execute(
        "SELECT a.app_id, f.hour, f.factor FROM app a JOIN app_hour_factor f ON f.app_id = a.app_id "
        "WHERE a.category IN ('SHORT_VIDEO', 'SOCIAL', 'VIDEO_STREAMING')"
    ).fetchall()
    by_app: dict[str, dict[int, float]] = defaultdict(dict)
    for r in rows:
        by_app[r["app_id"]][r["hour"]] = r["factor"]
    assert by_app and all(max(h[e] for e in EVENING) > 2 * h[NIGHT] for h in by_app.values())


def test_towns_have_different_favourite_apps(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT t.town, s.app_id, AVG(s.user_share) AS u FROM tower_app_share s JOIN tower t ON t.enodeb_name = s.enodeb_name "
        "WHERE s.app_id != 'whatsapp' GROUP BY t.town, s.app_id"
    ).fetchall()
    best: dict[str, tuple[float, str]] = {}
    for r in rows:
        if r["town"] not in best or r["u"] > best[r["town"]][0]:
            best[r["town"]] = (r["u"], r["app_id"])
    assert len({app for _, app in best.values()}) >= 3


def test_the_same_seed_gives_the_same_usage(db_file: Path, tmp_path: Path) -> None:
    other = build_test_db(tmp_path)
    query = "SELECT * FROM tower_app_share ORDER BY 1, 2"
    with sqlite3.connect(db_file) as a, sqlite3.connect(other) as b:
        assert a.execute(query).fetchall() == b.execute(query).fetchall()
