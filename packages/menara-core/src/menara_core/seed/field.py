"""Synthetic field workforce: fictional technicians at the drone depots, with skills, shifts and spare parts.

Five technicians per depot (the six drone depots from the scenario), each with one to three skills and one of three
shifts; two per depot work 06:00 to 18:00 so the day has cover. Spare parts are invented stock per depot; the Kota Bharu
depot (nearest the flood) has a generator and batteries. Names are fictional and end in "(synthetic)". Own random stream.
"""

from __future__ import annotations

import random
import sqlite3

from menara_core.scenario import Scenario

SKILLS = ["POWER", "RAN", "FIBRE", "CIVIL"]
PARTS = ["GENERATOR", "RECTIFIER", "BATTERY", "ANTENNA"]
FIRST = ["Aiman", "Wei Jie", "Priya", "Hakim", "Mei Ling", "Karthik", "Nurul", "Farid", "Siew Lan", "Ravi", "Aisyah", "Jason", "Dewi", "Imran", "Lim", "Suria"]
LAST = ["Rahman", "Tan", "Nair", "Salleh", "Lee", "Pillai", "Ismail", "Wong", "Kumar", "Hassan", "Ong", "Abdullah", "Chin", "Raj", "Yusof", "Lau"]
SHIFTS = [(6, 18), (6, 18), (8, 20), (18, 6), (18, 6)]  # per depot: two early, one mid, two night
PER_DEPOT = len(SHIFTS)
KOTA_BHARU_DEPOT = "DEP-KTBH"


def build_field(conn: sqlite3.Connection, seed: int, scenario: Scenario) -> None:
    rng = random.Random(f"{seed}:field")
    used: set[str] = set()
    techs: list[tuple[str, str, str, float, float, str, int, int]] = []
    parts: list[tuple[str, str, int]] = []
    number = 0
    for depot in scenario.drone.depots:
        for index, (start, end) in enumerate(SHIFTS):
            while True:
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)} (synthetic)"
                if name not in used:
                    used.add(name)
                    break
            skills = {SKILLS[index % len(SKILLS)]} | set(rng.sample(SKILLS, rng.randint(0, 2)))
            if index == 0:
                skills.add("POWER")  # every depot has a power technician on the early shift
            number += 1
            techs.append((f"TECH-{number:03d}", name, depot.id, depot.lat, depot.lng, ",".join(sorted(skills)), start, end))
        for part in PARTS:
            parts.append((depot.id, part, rng.randint(0, 4)))
    parts = [(d, p, max(q, {"GENERATOR": 1, "BATTERY": 2}.get(p, 0)) if d == KOTA_BHARU_DEPOT else q) for d, p, q in parts]
    conn.executemany("INSERT INTO technician VALUES (?, ?, ?, ?, ?, ?, ?, ?)", techs)
    conn.executemany("INSERT INTO spare_part VALUES (?, ?, ?)", parts)