"""Synthetic critical sites (clinics, police, schools, SLA customers) and per-tower subscriber estimates."""

from __future__ import annotations

import random
import sqlite3

from menara_core.geo import haversine_km
from menara_core.scenario import Scenario
from menara_core.seed.towers import TOWNS, TowerRow

EMERGENCY_KINDS = {"HOSPITAL", "CLINIC", "POLICE", "FIRE"}
PRIORITY = {"HOSPITAL": 1, "CLINIC": 1, "POLICE": 1, "FIRE": 1, "ENTERPRISE": 2, "SCHOOL": 3}
# (kind, count, label) per town. Names are fictional.
PER_TOWN = [("HOSPITAL", 1, "Hospital"), ("CLINIC", 2, "Clinic"), ("POLICE", 1, "Police Station"),
            ("SCHOOL", 3, "School"), ("ENTERPRISE", 1, "Enterprise (SLA)")]
URBAN_CODES = {"KULP", "SHAH", "GTWN", "JBHR", "KKIN", "KCHG", "IPOH"}
SUBSCRIBERS_RANGE = (300, 1800)


def _insert(
    conn: sqlite3.Connection, site_id: str, name: str, kind: str, state: str, lat: float, lng: float, serving: str
) -> None:
    conn.execute(
        "INSERT INTO critical_site VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (site_id, name, kind, state, lat, lng, PRIORITY[kind], int(kind in EMERGENCY_KINDS), serving),
    )


def build_sites(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow]) -> None:
    cluster_names = {t.enodeb for t in scenario.cluster.towers}
    by_name = {t.enodeb_name: t for t in towers}
    for tower in towers:
        if tower.enodeb_name in scenario.subscribers_est:
            estimate = scenario.subscribers_est[tower.enodeb_name]
        else:
            low, high = SUBSCRIBERS_RANGE
            estimate = int(rng.randint(low, high) * (1.5 if tower.enodeb_name[:4] in URBAN_CODES else 1.0))
        conn.execute("INSERT INTO tower_subscribers VALUES (?, ?)", (tower.enodeb_name, estimate))

    for code, town, state, _lat, _lng, _w, _r in TOWNS:
        local = [t for t in towers if t.town == town and t.enodeb_name not in cluster_names]
        if not local:
            continue
        index = 0
        for kind, count, label in PER_TOWN:
            for _ in range(count):
                index += 1
                anchor = rng.choice(local)
                lat, lng = anchor.lat + rng.uniform(-0.01, 0.01), anchor.lng + rng.uniform(-0.01, 0.01)
                serving = min(local, key=lambda t: haversine_km(lat, lng, t.lat, t.lng))
                _insert(conn, f"CS-{code}-{index:02d}", f"{town} {label} {index} (synthetic)", kind, state,
                        round(lat, 5), round(lng, 5), serving.enodeb_name)

    for site in scenario.sites:
        assert site.serving in by_name, f"scenario site {site.id} names unknown tower {site.serving}"
        _insert(conn, site.id, site.name, site.kind, scenario.cluster.state, site.lat, site.lng, site.serving)
