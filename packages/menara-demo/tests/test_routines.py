"""Routines: counts and sentences worked out from a long trail, so the model only has to word them."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from menara_demo.routines import completed_weekends, routines_for, tower_stats

WINDOW_START = datetime.fromisoformat("2026-10-17T07:12:00+08:00")  # a Saturday, four weeks before the clock at minute 12
WINDOW_MIN = 40320
NOW = WINDOW_START + timedelta(minutes=WINDOW_MIN)  # Saturday 2026-11-14 07:12


def at(day: int, hour: int, minute: int = 0) -> datetime:
    """day 0 is the first Saturday (2026-10-17)."""
    return WINDOW_START.replace(hour=hour, minute=minute) + timedelta(days=day)


def trail(stays: list[tuple[str, datetime, int]]) -> dict[str, Any]:
    """stays: (tower, arrival, minutes); each stay ends where the next begins, the last one is current."""
    segments = []
    for index, (tower, arrival, minutes) in enumerate(stays):
        last = index == len(stays) - 1
        segments.append(
            {
                "enodeb_name": tower,
                "arrived_at": arrival.isoformat(),
                "left_at": None if last else stays[index + 1][1].isoformat(),
                "duration_min": minutes,
                "current": last,
            }
        )
    return {
        "window_start": WINDOW_START.isoformat(),
        "window_min": WINDOW_MIN,
        "segments": segments,
    }


def week_of_stays(visits: list[tuple[int, int, str, int]]) -> dict[str, Any]:
    """visits: (day, hour, tower, minutes) away from home; home fills the gaps."""
    stays: list[tuple[str, datetime, int]] = [("HOME-0001", WINDOW_START, 600)]
    for day, hour, tower, minutes in visits:
        stays.append((tower, at(day, hour), minutes))
        stays.append(("HOME-0001", at(day, hour) + timedelta(minutes=minutes), 600))
    stays.append(("HOME-0001", at(27, 22), 300))
    return trail(stays)


NEARBY = {
    "MALL-0001": [{"name": "Tawau Mall 3 (synthetic)", "kind": "MALL", "distance_km": 0.4}],
    "WORK-0001": [{"name": "Tawau School 7 (synthetic)", "kind": "SCHOOL", "distance_km": 0.9}],
    "HOME-0001": [{"name": "Tawau Clinic 2 (synthetic)", "kind": "CLINIC", "distance_km": 1.2}],
}


def test_a_four_week_window_has_four_completed_weekends_and_today_is_not_one() -> None:
    weekends = completed_weekends(WINDOW_START, WINDOW_MIN)
    assert [d.isoformat() for d in weekends] == ["2026-10-17", "2026-10-24", "2026-10-31", "2026-11-07"]


def test_a_weekend_habit_names_the_place_the_counts_and_the_usual_time() -> None:
    data = week_of_stays([(0, 11, "MALL-0001", 150), (7, 11, "MALL-0001", 150), (14, 12, "MALL-0001", 150), (21, 11, "MALL-0001", 150)])
    found = [r for r in routines_for(data, NEARBY) if r["kind"] == "weekend"]
    assert len(found) == 1
    assert found[0]["tower"] == "MALL-0001" and found[0]["days"] == 4 and found[0]["of"] == 4
    assert found[0]["sentence"] == "Weekends: near Tawau Mall 3 (synthetic) on 4 of 4 weekends, usually about 2 h 30 min from about 11:00"


def test_a_weekend_habit_needs_three_weekend_days_across_two_weekends() -> None:
    two_days = week_of_stays([(0, 11, "MALL-0001", 150), (1, 11, "MALL-0001", 150)])
    assert [r for r in routines_for(two_days, NEARBY) if r["kind"] == "weekend"] == []
    three_days = week_of_stays([(0, 11, "MALL-0001", 150), (1, 11, "MALL-0001", 150), (7, 11, "MALL-0001", 150)])
    found = [r for r in routines_for(three_days, NEARBY) if r["kind"] == "weekend"]
    assert len(found) == 1 and found[0]["days"] == 2 and found[0]["of"] == 4  # two distinct weekends


def test_a_weekday_habit_needs_five_weekdays() -> None:
    four = week_of_stays([(day, 8, "WORK-0001", 540) for day in (2, 3, 4, 5)])
    assert [r for r in routines_for(four, NEARBY) if r["kind"] == "weekday"] == []
    five = week_of_stays([(day, 8, "WORK-0001", 540) for day in (2, 3, 4, 5, 6)])
    found = [r for r in routines_for(five, NEARBY) if r["kind"] == "weekday"]
    assert len(found) == 1 and found[0]["days"] == 5
    assert found[0]["sentence"].startswith("Weekdays: near Tawau School 7 (synthetic) on 5 weekdays")


def test_a_stay_under_45_minutes_is_transit_not_a_stop() -> None:
    for minutes in (25, 30, 44):  # 30 minutes is how long a commute spends on the tower on the way
        quick = week_of_stays([(day, 8, "WORK-0001", minutes) for day in (2, 3, 4, 5, 6, 9)])
        assert [r for r in routines_for(quick, NEARBY) if r["kind"] == "weekday"] == []
        assert "WORK-0001" not in tower_stats(quick)
    assert "WORK-0001" in tower_stats(week_of_stays([(2, 8, "WORK-0001", 45)]))


def test_weekend_and_weekday_times_are_worked_out_separately() -> None:
    visits = [(day, 8, "MALL-0001", 30) for day in (2, 3, 4)] + [(day, 11, "MALL-0001", 150) for day in (0, 7, 14)]
    visits += [(day, 9, "MALL-0001", 50) for day in (5, 6, 9)]
    found = [r for r in routines_for(week_of_stays(sorted(visits)), NEARBY) if r["kind"] == "weekend"]
    assert len(found) == 1 and found[0]["sentence"].endswith("usually about 2 h 30 min from about 11:00")


def test_todays_unfinished_weekend_does_not_count() -> None:
    data = trail([("HOME-0001", WINDOW_START, 600), ("MALL-0001", at(27, 22), 120)])  # not a weekend day at all
    data["segments"][-1]["arrived_at"] = at(28, 7, 0).isoformat()  # Saturday 2026-11-14: the clock's own weekend
    assert tower_stats(data)["MALL-0001"]["weekend_days"] == 0


def test_the_tower_where_the_time_is_spent_is_probably_home_and_gets_no_habit_line() -> None:
    data = week_of_stays([(0, 11, "MALL-0001", 150)] * 1)
    found = routines_for(data, NEARBY)
    home = [r for r in found if r["kind"] == "home"]
    assert len(home) == 1 and home[0]["tower"] == "HOME-0001" and "probably home" in home[0]["sentence"]
    assert all(r["tower"] != "HOME-0001" for r in found if r["kind"] != "home")


def test_a_place_with_no_known_site_nearby_says_so() -> None:
    data = week_of_stays([(day, 8, "WORK-0001", 540) for day in (2, 3, 4, 5, 6)])
    found = [r for r in routines_for(data, {"WORK-0001": []}) if r["kind"] == "weekday"]
    assert "no known site" in found[0]["sentence"]


def test_typical_arrival_hour_and_stay_are_medians() -> None:
    data = week_of_stays([(2, 8, "WORK-0001", 500), (3, 9, "WORK-0001", 540), (4, 8, "WORK-0001", 520), (5, 10, "WORK-0001", 530), (6, 8, "WORK-0001", 510)])
    stats = tower_stats(data)["WORK-0001"]
    assert stats["weekday_typical_hour"] == 8 and stats["weekday_typical_minutes"] == 520 and stats["weekday_days"] == 5
    assert stats["weekend_typical_hour"] is None