"""Synthetic app usage: which apps people use, when, and how much data they take. Invented numbers, labelled synthetic.

Three base tables, read by usage-mcp: `app` (the catalogue), `app_hour_factor` (how active an app is in each hour,
1.0 at its peak) and `tower_app_share` (per tower: the share of its users who use the app in a day, and the app's
share of the tower's data). There is no per-person data. Each town gets its own favourite app so different places
have a different number one. Drawn from its own random stream so every older table is unchanged.
"""

from __future__ import annotations

import random
import sqlite3

from menara_core.seed.sites import URBAN_CODES
from menara_core.seed.towers import TowerRow

# (app_id, name, category, daily reach urban, daily reach elsewhere, relative data per user)
APPS: list[tuple[str, str, str, float, float, float]] = [
    ("whatsapp", "WhatsApp", "MESSAGING", 0.92, 0.90, 0.35),
    ("facebook", "Facebook", "SOCIAL", 0.75, 0.80, 0.90),
    ("tiktok", "TikTok", "SHORT_VIDEO", 0.70, 0.62, 1.60),
    ("youtube", "YouTube", "VIDEO_STREAMING", 0.68, 0.60, 2.40),
    ("instagram", "Instagram", "SOCIAL", 0.55, 0.40, 1.10),
    ("shopee", "Shopee", "COMMERCE", 0.45, 0.40, 0.60),
    ("gmaps", "Google Maps", "MOBILITY", 0.40, 0.30, 0.25),
    ("grab", "Grab", "MOBILITY", 0.35, 0.15, 0.15),
    ("telegram", "Telegram", "MESSAGING", 0.30, 0.22, 0.30),
    ("spotify", "Spotify", "MUSIC", 0.28, 0.15, 0.50),
    ("netflix", "Netflix", "VIDEO_STREAMING", 0.22, 0.10, 3.00),
    ("mlbb", "Mobile Legends", "GAMING", 0.20, 0.25, 0.80),
    ("threads", "Threads", "SOCIAL", 0.18, 0.08, 0.40),
    ("x", "X", "SOCIAL", 0.15, 0.08, 0.35),
]
FAVOURITES = ["tiktok", "facebook", "youtube", "instagram", "shopee"]
RISERS = ["threads", "mlbb", "telegram", "x", "spotify", "netflix"]
FAVOURITE_BOOST = 1.3
FAVOURITE_FLOOR = 0.86
FAVOURITE_CEILING = 0.9  # a town's favourite is clearly its leading app after the messengers
RISER_BOOST = 2.0  # an app that is catching on in the town
MAX_REACH = 0.98
NOISE = 0.1

# Hourly activity, 0 to 1, by category (index = hour of day, 0 to 23).
_FLAT = [0.10, 0.07, 0.05, 0.04, 0.04, 0.06, 0.14, 0.30, 0.42, 0.40, 0.42, 0.50, 0.62, 0.55, 0.48, 0.47, 0.52, 0.60, 0.68, 0.78, 0.92, 1.00, 0.80, 0.35]
CURVES: dict[str, list[float]] = {
    "SHORT_VIDEO": [0.20, 0.12, 0.07, 0.05, 0.05, 0.07, 0.14, 0.26, 0.34, 0.32, 0.34, 0.45, 0.62, 0.52, 0.45, 0.46, 0.52, 0.62, 0.74, 0.88, 1.00, 0.98, 0.78, 0.40],
    "SOCIAL": [0.14, 0.09, 0.06, 0.05, 0.05, 0.08, 0.20, 0.42, 0.50, 0.46, 0.46, 0.55, 0.70, 0.58, 0.50, 0.50, 0.55, 0.64, 0.74, 0.86, 0.98, 1.00, 0.76, 0.30],
    "MESSAGING": [0.12, 0.08, 0.06, 0.05, 0.06, 0.12, 0.34, 0.62, 0.70, 0.64, 0.62, 0.68, 0.80, 0.70, 0.64, 0.62, 0.66, 0.74, 0.84, 0.94, 1.00, 0.96, 0.62, 0.26],
    "VIDEO_STREAMING": [0.18, 0.10, 0.06, 0.04, 0.04, 0.05, 0.08, 0.14, 0.18, 0.18, 0.20, 0.28, 0.40, 0.34, 0.30, 0.32, 0.38, 0.50, 0.66, 0.86, 1.00, 0.98, 0.80, 0.42],
    "MUSIC": [0.06, 0.04, 0.03, 0.03, 0.04, 0.10, 0.40, 0.86, 1.00, 0.66, 0.52, 0.50, 0.56, 0.50, 0.46, 0.50, 0.64, 0.90, 0.96, 0.60, 0.44, 0.36, 0.24, 0.12],
    "GAMING": [0.22, 0.14, 0.08, 0.05, 0.04, 0.04, 0.05, 0.08, 0.10, 0.10, 0.12, 0.18, 0.30, 0.28, 0.26, 0.30, 0.40, 0.54, 0.72, 0.92, 1.00, 0.96, 0.74, 0.40],
    "COMMERCE": [0.10, 0.05, 0.03, 0.02, 0.02, 0.03, 0.08, 0.20, 0.30, 0.34, 0.38, 0.50, 0.82, 0.60, 0.46, 0.44, 0.48, 0.56, 0.70, 0.86, 1.00, 0.94, 0.58, 0.24],
    "MOBILITY": [0.06, 0.03, 0.02, 0.02, 0.03, 0.10, 0.34, 0.86, 1.00, 0.54, 0.36, 0.40, 0.58, 0.46, 0.36, 0.40, 0.62, 0.96, 0.98, 0.58, 0.40, 0.30, 0.20, 0.10],
}


def build_usage(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    rng = random.Random(f"{seed}:usage")
    conn.executemany("INSERT INTO app VALUES (?, ?, ?)", [(a[0], a[1], a[2]) for a in APPS])
    conn.executemany(
        "INSERT INTO app_hour_factor VALUES (?, ?, ?)",
        [(a[0], hour, CURVES.get(a[2], _FLAT)[hour]) for a in APPS for hour in range(24)],
    )
    towns = sorted({t.town for t in towers})
    favourite_of_town = {town: rng.choice(FAVOURITES) for town in towns}
    riser_of_town = {town: rng.choice(RISERS) for town in towns}
    rows: list[tuple[str, str, float, float]] = []
    for tower in towers:
        urban = tower.enodeb_name[:4] in URBAN_CODES
        reach: dict[str, float] = {}
        for app_id, _, _, urban_reach, other_reach, _ in APPS:
            value = urban_reach if urban else other_reach
            if app_id == favourite_of_town[tower.town]:
                value = min(FAVOURITE_CEILING, max(value * FAVOURITE_BOOST, FAVOURITE_FLOOR))
            elif app_id == riser_of_town[tower.town]:
                value *= RISER_BOOST
            reach[app_id] = round(min(MAX_REACH, value * rng.uniform(1 - NOISE, 1 + NOISE)), 4)
        volume = {a[0]: reach[a[0]] * a[5] for a in APPS}
        total = sum(volume.values())
        rows += [(tower.enodeb_name, app_id, reach[app_id], volume[app_id] / total) for app_id in reach]
    conn.executemany("INSERT INTO tower_app_share VALUES (?, ?, ?, ?)", rows)