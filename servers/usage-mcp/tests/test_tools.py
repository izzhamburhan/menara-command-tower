"""usage-mcp tools: what people use in a circle or on a tower. Invented numbers; never per person."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable

import pytest
from menara_core.errors import InvalidInputError, NotFoundError
from usage_mcp import tools


def a_tower(conn: sqlite3.Connection, index: int = 0) -> sqlite3.Row:
    return conn.execute("SELECT enodeb_name, lat, lng, town FROM tower ORDER BY enodeb_name LIMIT 1 OFFSET ?", (index,)).fetchone()  # type: ignore[no-any-return]


def circle(conn: sqlite3.Connection) -> tuple[float, float]:
    row = conn.execute(
        "SELECT t.lat, t.lng FROM tower t JOIN tower_subscribers s ON s.enodeb_name = t.enodeb_name ORDER BY s.subscribers_est DESC LIMIT 1"
    ).fetchone()
    return float(row["lat"]), float(row["lng"])


def test_the_top_apps_are_ranked_by_users_and_by_data(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    by_users = tools.top_apps_in_area(conn, lat, lng, 5.0, rank_by="users", hour=21).data
    assert by_users.towers_counted >= 1 and not by_users.withheld
    assert [a.rank for a in by_users.apps] == list(range(1, len(by_users.apps) + 1))
    assert [a.users_est for a in by_users.apps] == sorted((a.users_est for a in by_users.apps), reverse=True)
    by_data = tools.top_apps_in_area(conn, lat, lng, 5.0, rank_by="data", hour=21).data
    assert [a.data_share_pct for a in by_data.apps] == sorted((a.data_share_pct for a in by_data.apps), reverse=True)
    assert by_data.apps[0].category in {"VIDEO_STREAMING", "SHORT_VIDEO"}


def test_limit_and_fields(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    data = tools.top_apps_in_area(conn, lat, lng, 5.0, hour=12, limit=3).data
    assert len(data.apps) == 3
    first = data.apps[0]
    assert first.app_id and first.name and first.category and 0 < first.reach_pct <= 100 and first.users_est > 0


def test_the_category_shares_sum_to_100(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    for hour in (4, 12, 21):
        data = tools.top_apps_in_area(conn, lat, lng, 8.0, hour=hour).data
        assert abs(sum(c.data_share_pct for c in data.categories) - 100.0) < 0.2
        assert [c.data_share_pct for c in data.categories] == sorted((c.data_share_pct for c in data.categories), reverse=True)


def test_users_and_reach_follow_the_hour(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    night = tools.top_apps_in_area(conn, lat, lng, 5.0, hour=4, limit=14).data
    evening = tools.top_apps_in_area(conn, lat, lng, 5.0, hour=21, limit=14).data
    tiktok_night = next(a for a in night.apps if a.app_id == "tiktok").users_est
    tiktok_evening = next(a for a in evening.apps if a.app_id == "tiktok").users_est
    assert tiktok_evening > 3 * tiktok_night
    assert evening.busiest_hour == night.busiest_hour and evening.busiest_hour in range(18, 23)


def test_the_default_hour_comes_from_the_scenario_clock(conn: sqlite3.Connection, set_clock: Callable[[int], None]) -> None:
    lat, lng = circle(conn)
    set_clock(0)
    assert tools.top_apps_in_area(conn, lat, lng, 5.0).data.hour == 7
    set_clock(14 * 60)
    assert tools.top_apps_in_area(conn, lat, lng, 5.0).data.hour == 21
    assert tools.top_apps_in_area(conn, lat, lng, 5.0, hour=3).data.hour == 3


def test_towns_have_different_top_apps_outside_the_messengers(conn: sqlite3.Connection) -> None:
    tops = set()
    towns = conn.execute("SELECT MIN(enodeb_name) AS name FROM tower GROUP BY town").fetchall()
    for row in towns:
        apps = tools.get_tower_apps(conn, row["name"], hour=21, limit=14).data.apps
        tops.add(next(a.app_id for a in apps if a.category != "MESSAGING"))
    assert len(tops) >= 2


def test_an_area_with_fewer_than_5_estimated_users_is_withheld() -> None:
    assert tools.withhold(4) is True and tools.withhold(5) is False and tools.MIN_ESTIMATED_USERS == 5


def test_an_empty_circle_gives_zero_towers_and_a_warning(conn: sqlite3.Connection) -> None:
    env = tools.top_apps_in_area(conn, 0.0, 100.0, 1.0, hour=12)
    assert env.data.towers_counted == 0 and env.data.apps == [] and env.warnings


def test_tower_apps_for_one_tower_and_an_unknown_tower_is_not_found(conn: sqlite3.Connection) -> None:
    tower = a_tower(conn)
    data = tools.get_tower_apps(conn, tower["enodeb_name"], hour=21).data
    assert data.enodeb_name == tower["enodeb_name"] and data.towers_counted == 1 and data.apps
    with pytest.raises(NotFoundError):
        tools.get_tower_apps(conn, "ZZZZ-9999")


def test_app_trend_has_24_points_and_a_peak_hour_and_accepts_id_or_name_in_any_case(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    by_id = tools.app_trend(conn, lat, lng, 5.0, "tiktok").data
    by_name = tools.app_trend(conn, lat, lng, 5.0, "TikTok").data
    assert [p.hour for p in by_id.points] == list(range(24)) and by_id.points == by_name.points
    assert by_id.peak_hour == max(by_id.points, key=lambda p: p.users_est).hour and by_id.peak_hour in range(18, 23)
    assert by_id.name == "TikTok"


def test_an_unknown_app_lists_the_valid_ids(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    with pytest.raises(InvalidInputError, match="tiktok"):
        tools.app_trend(conn, lat, lng, 5.0, "nonexistent")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radius_km": 0.0}, {"radius_km": 101.0}, {"hour": 24}, {"hour": -1}, {"limit": 0}, {"limit": 21}, {"rank_by": "x"},
        {"lat": 91.0}, {"lng": 181.0},
    ],
)
def test_bad_numbers_are_invalid_input(conn: sqlite3.Connection, kwargs: dict[str, object]) -> None:
    args: dict[str, object] = {"lat": 4.0, "lng": 100.0, "radius_km": 5.0}
    args.update(kwargs)
    with pytest.raises(InvalidInputError):
        tools.top_apps_in_area(conn, **args)  # type: ignore[arg-type]


def test_every_answer_is_synthetic_and_has_evidence_and_no_subscriber_hash(conn: sqlite3.Connection) -> None:
    lat, lng = circle(conn)
    tower = a_tower(conn)
    for env in (
        tools.top_apps_in_area(conn, lat, lng, 5.0, hour=21),
        tools.get_tower_apps(conn, tower["enodeb_name"], hour=21),
        tools.app_trend(conn, lat, lng, 5.0, "tiktok"),
    ):
        assert env.synthetic is True and env.evidence
        text = json.dumps(env.model_dump(mode="json")).lower()
        assert "msisdn" not in text and "synthetic" in text
