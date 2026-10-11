"""Routines worked out from a long trail: the counts are computed here, so a model only has to word them.

A routine is a place a subscriber returns to: the home tower (where most of the time is spent), a weekday place
(at least 5 weekdays) or a weekend place (at least 3 weekend days across at least 2 completed weekends).
A stay under 45 minutes is transit, not a stop (a commute spends about 30 minutes on the tower on the way). Locations are cell level, so a place is described as "near" its sites.
All data is synthetic.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

MIN_STAY_MIN = 45
MIN_WEEKDAYS = 5
MIN_WEEKEND_DAYS = 3
MIN_WEEKENDS = 2
HOME_SHARE = 0.4
MAX_SITES_NAMED = 2

Stats = dict[str, Any]
Routine = dict[str, Any]


def completed_weekends(window_start: datetime, window_min: int) -> list[date]:
    """Saturdays of the weekends that began and ended inside the window (the clock's own weekend is not complete)."""
    window_end = window_start + timedelta(minutes=window_min)
    saturdays: list[date] = []
    day = window_start.date()
    while day < window_end.date():
        if day.weekday() == 5 and day + timedelta(days=1) < window_end.date():
            saturdays.append(day)
        day += timedelta(days=1)
    return saturdays


def tower_stats(trail: dict[str, Any]) -> dict[str, Stats]:
    """Per tower where the subscriber stayed at least 45 minutes: time spent and the days of arrival."""
    window_start = datetime.fromisoformat(trail["window_start"])
    weekends = set(completed_weekends(window_start, int(trail["window_min"])))
    total: dict[str, int] = defaultdict(int)
    weekday_days: dict[str, set[date]] = defaultdict(set)
    weekend_days: dict[str, set[date]] = defaultdict(set)
    hours: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"weekday": [], "weekend": []})
    stays: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"weekday": [], "weekend": []})
    for seg in trail["segments"]:
        minutes = int(seg["duration_min"])
        if minutes < MIN_STAY_MIN:
            continue
        tower = seg["enodeb_name"]
        total[tower] += minutes
        arrived = datetime.fromisoformat(seg["arrived_at"])
        if arrived < window_start:
            continue  # it began before the window: time counts, but not as an arrival
        if arrived.weekday() < 5:
            weekday_days[tower].add(arrived.date())
            hours[tower]["weekday"].append(arrived.hour)
            stays[tower]["weekday"].append(minutes)
        else:
            saturday = arrived.date() - timedelta(days=arrived.weekday() - 5)
            if saturday in weekends:
                weekend_days[tower].add(arrived.date())
                hours[tower]["weekend"].append(arrived.hour)
                stays[tower]["weekend"].append(minutes)
    result: dict[str, Stats] = {}
    for tower, minutes in total.items():
        result[tower] = {
            "total_minutes": minutes,
            "weekday_days": len(weekday_days[tower]),
            "weekend_days": len(weekend_days[tower]),
            "weekend_weekends": len({d - timedelta(days=d.weekday() - 5) for d in weekend_days[tower]}),
            **{
                f"{part}_typical_{what}": (statistics.median_low(values[tower][part]) if values[tower][part] else None)
                for part in ("weekday", "weekend")
                for what, values in (("hour", hours), ("minutes", stays))
            },
        }
    return result


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours and rest:
        return f"{hours} h {rest} min"
    return f"{hours} h" if hours else f"{rest} min"


def _near(sites: list[dict[str, Any]]) -> str:
    names = [str(s["name"]) for s in sites[:MAX_SITES_NAMED]]
    return "near " + (" and ".join(names) if names else "no known site")


def _usual(stats: Stats, part: str) -> str:
    minutes, hour = stats[f"{part}_typical_minutes"], stats[f"{part}_typical_hour"]
    if minutes is None or hour is None:
        return ""
    return f", usually about {_duration(minutes)} from about {hour:02d}:00"


def routines_for(trail: dict[str, Any], nearby: dict[str, list[dict[str, Any]]]) -> list[Routine]:
    """The routine lines for one trail. `nearby` maps a tower to its known sites, nearest first."""
    stats = tower_stats(trail)
    if not stats:
        return []
    window_start = datetime.fromisoformat(trail["window_start"])
    weekends = len(completed_weekends(window_start, int(trail["window_min"])))
    everything = sum(s["total_minutes"] for s in stats.values())
    home = max(stats, key=lambda t: stats[t]["total_minutes"])
    found: list[Routine] = []
    if stats[home]["total_minutes"] >= HOME_SHARE * everything:
        found.append(
            {
                "tower": home,
                "kind": "home",
                "days": None,
                "of": None,
                "sites": [str(s["name"]) for s in nearby.get(home, [])[:MAX_SITES_NAMED]],
                "sentence": f"Most of the time: probably home, {_near(nearby.get(home, []))}",
            }
        )
    for tower in sorted(stats):
        if tower == home:
            continue
        s, sites = stats[tower], nearby.get(tower, [])
        if s["weekend_days"] >= MIN_WEEKEND_DAYS and s["weekend_weekends"] >= MIN_WEEKENDS:
            found.append(
                {
                    "tower": tower,
                    "kind": "weekend",
                    "days": s["weekend_weekends"],
                    "of": weekends,
                    "sites": [str(x["name"]) for x in sites[:MAX_SITES_NAMED]],
                    "sentence": f"Weekends: {_near(sites)} on {s['weekend_weekends']} of {weekends} weekends{_usual(s, 'weekend')}",
                }
            )
        if s["weekday_days"] >= MIN_WEEKDAYS:
            found.append(
                {
                    "tower": tower,
                    "kind": "weekday",
                    "days": s["weekday_days"],
                    "of": None,
                    "sites": [str(x["name"]) for x in sites[:MAX_SITES_NAMED]],
                    "sentence": f"Weekdays: {_near(sites)} on {s['weekday_days']} weekdays{_usual(s, 'weekday')}",
                }
            )
    return found