"""Synthetic crowd events: fictional festivals, matches, concerts and the balik kampung rush, a few hours to days ahead.

About 25 events near existing towers, with invented names ending in "(synthetic)" and crowd sizes. A scripted derby
in Kota Bharu is the next big match. Own random stream so every older table is unchanged.
"""

from __future__ import annotations

import random
import sqlite3

from menara_core.seed.towers import TowerRow

COUNT = 24
KINDS = {
    "FESTIVAL": ("{town} Harvest Festival (synthetic)", (5000, 30000), (240, 480)),
    "MATCH": ("{town} Derby Football Match (synthetic)", (20000, 60000), (150, 200)),
    "CONCERT": ("{town} Open-Air Concert (synthetic)", (10000, 40000), (180, 300)),
    "EXODUS": ("Balik Kampung Rush at {town} (synthetic)", (30000, 100000), (600, 900)),
}
START_RANGE = (180, 5760)  # minutes after T0: a few hours to four days ahead
VENUE_SPREAD_DEG = 0.01
SCRIPTED = ("Kota Bharu Derby Football Match (synthetic)", "MATCH", "Kota Bharu", 2100, 2280, 42000)  # 18:00 the next day


def build_events(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    rng = random.Random(f"{seed}:events")
    by_town: dict[str, list[TowerRow]] = {}
    for t in towers:
        if t.enodeb_name[:4] != "KKRI":
            by_town.setdefault(t.town, []).append(t)
    rows: list[tuple[str, str, str, float, float, float, int, int, int]] = []
    used: set[str] = set()

    def add(name: str, kind: str, town: str, start: int, end: int, attendance: int) -> None:
        if name in used or town not in by_town:
            return
        used.add(name)
        anchor = rng.choice(by_town[town])
        rows.append(
            (name, kind, town, round(anchor.lat + rng.uniform(-VENUE_SPREAD_DEG, VENUE_SPREAD_DEG), 5),
             round(anchor.lng + rng.uniform(-VENUE_SPREAD_DEG, VENUE_SPREAD_DEG), 5), round(rng.uniform(0.5, 2.5), 1), start, end, attendance)
        )

    name, kind, town, start, end, attendance = SCRIPTED
    add(name, kind, town, start, end, attendance)
    towns = sorted(by_town)
    for _ in range(COUNT):
        kind = rng.choice(sorted(KINDS))
        pattern, crowd, length = KINDS[kind]
        town = rng.choice(towns)
        start = rng.randint(*START_RANGE)
        add(pattern.format(town=town), kind, town, start, start + rng.randint(*length), round(rng.randint(*crowd), -2))
    ordered = sorted(rows, key=lambda r: (r[6], r[0]))
    conn.executemany(
        "INSERT INTO crowd_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(f"EVT-{i:03d}", *row) for i, row in enumerate(ordered, start=1)],
    )
