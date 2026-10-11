"""Synthetic tower energy: how much power a tower draws, and how long its battery and generator last.

One row per tower in `tower_energy`, read by energy-mcp. Invented numbers: a macro tower draws more than a rooftop
one, urban towers a little more, and about 40% of towers have a diesel generator. The flood tower has a generator with
only about nine hours of fuel. Drawn from its own random stream so every older table is unchanged.
"""

from __future__ import annotations

import random
import sqlite3

from menara_core.seed.sites import URBAN_CODES
from menara_core.seed.towers import TowerRow

BASE_KW = {"macro": 3.2, "rooftop": 1.6, "pole": 0.9}
BATTERY_KWH = {"macro": 14.0, "rooftop": 7.0, "pole": 3.5}
URBAN_FACTOR = 1.15
NOISE = 0.08
GENSET_SHARE = 0.4
GENSET_FUEL_L = (80.0, 300.0)
GENSET_L_PER_H = (6.0, 11.0)
FLOOD_TOWER = "KKRI-0142"  # the scenario's flooded tower: a generator with limited fuel, reachable only by boat
FLOOD_FUEL_L, FLOOD_L_PER_H = 90.0, 10.0


def build_energy(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    rng = random.Random(f"{seed}:energy")
    rows: list[tuple[str, float, float, int, float, float]] = []
    for tower in towers:
        kind = tower.tower_type if tower.tower_type in BASE_KW else "macro"
        urban = URBAN_FACTOR if tower.enodeb_name[:4] in URBAN_CODES else 1.0
        base = round(BASE_KW[kind] * urban * rng.uniform(1 - NOISE, 1 + NOISE), 2)
        battery = round(BATTERY_KWH[kind] * rng.uniform(1 - NOISE, 1 + NOISE), 1)
        has_genset = rng.random() < GENSET_SHARE and kind == "macro"
        fuel = round(rng.uniform(*GENSET_FUEL_L), 0) if has_genset else 0.0
        burn = round(rng.uniform(*GENSET_L_PER_H), 1) if has_genset else 0.0
        if tower.enodeb_name == FLOOD_TOWER:
            has_genset, fuel, burn = True, FLOOD_FUEL_L, FLOOD_L_PER_H
        rows.append((tower.enodeb_name, base, battery, int(has_genset), fuel, burn))
    conn.executemany("INSERT INTO tower_energy VALUES (?, ?, ?, ?, ?, ?)", rows)