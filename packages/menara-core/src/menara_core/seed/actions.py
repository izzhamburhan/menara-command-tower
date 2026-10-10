"""Seed data for the action domains: policy defaults, scripted RAN outcomes, drones and canned findings."""

from __future__ import annotations

import json
import random
import sqlite3

from menara_core.scenario import Scenario
from menara_core.seed.towers import TowerRow


def build_actions(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow]) -> None:
    policy = scenario.policy
    settings = {
        "kill_switch": "0",
        "auto_allow_max_subscribers": str(policy.auto_allow_max_subscribers),
        "auto_allow_min_confidence": str(policy.auto_allow_min_confidence),
        "peak_start_hour": str(policy.peak_start_hour),
        "peak_end_hour": str(policy.peak_end_hour),
        "max_actions_per_hour": str(policy.max_actions_per_hour),
        "token_ttl_s": str(policy.token_ttl_s),
    }
    conn.executemany("INSERT INTO policy_setting VALUES (?, ?)", sorted(settings.items()))

    conn.executemany(
        "INSERT INTO seed_meta VALUES (?, ?)",
        [
            ("drone_speed_kmh", str(scenario.drone.speed_kmh)),
            ("drone_inspect_min", str(scenario.drone.inspect_min)),
        ],
    )

    conn.executemany(
        "INSERT INTO ran_script VALUES (?, ?, ?, ?)",
        [(f.action, f.tower, f.attempt, f.efficacy) for f in scenario.ran.scripted_failures],
    )

    for depot in scenario.drone.depots:
        conn.executemany(
            "INSERT INTO drone VALUES (?, ?, ?, ?, ?)",
            [(drone, depot.id, depot.name, depot.lat, depot.lng) for drone in depot.drones],
        )

    scripted = scenario.drone.findings
    for tower in towers:
        if tower.enodeb_name in scripted:
            finding = scripted[tower.enodeb_name].model_dump()
        else:
            finding = {
                "access_road": {"status": "PASSABLE", "water_depth_m": 0.0, "passable_by": "CAR"},
                "tower_structure": "INTACT",
                "antenna_alignment": "ALIGNED",
                "power_cabinet": "OK",
                "genset": {"status": "OK", "access": "ROAD"},
                "hazards": [],
                "summary": "Site normal (synthetic).",
                "confidence": round(rng.uniform(0.88, 0.97), 2),
            }
        conn.execute("INSERT INTO drone_finding VALUES (?, ?)", (tower.enodeb_name, json.dumps(finding, sort_keys=True)))