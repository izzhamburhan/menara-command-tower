"""Synthetic business customers: fictional companies with an SLA on a tower, so an outage has a price.

One account per `ENTERPRISE` critical site, five fictional accounts on the flood cluster (the flooded tower `KKRI-0142`
has two), and up to two per town. Names are invented and end in "(synthetic)". Values, availability promises and
penalty rates are invented: the penalty is 1% of the monthly value per hour of outage. Own random stream.
"""

from __future__ import annotations

import random
import sqlite3

from menara_core.seed.towers import TowerRow

PLANS = ["Business Connect", "Business Connect Plus", "Critical Connect"]
SECTORS = ["Logistics", "Retail", "Manufacturing", "Hotel", "Cold Storage", "Education", "Property", "Food Processing"]
SLA_PCT = (99.5, 99.9, 99.95)
VALUE_RANGE = (3000.0, 40000.0)
PENALTY_SHARE = 0.01  # of the monthly value, per hour of outage
PER_TOWN = 2
# Fictional accounts on the flood cluster: (name, sector, tower, monthly value)
CLUSTER_ACCOUNTS = [
    ("Kuala Krai Cold Storage (synthetic)", "Cold Storage", "KKRI-0142", 28000.0),
    ("Dabong Timber Mill (synthetic)", "Manufacturing", "KKRI-0142", 17500.0),
    ("Kelantan Fresh Foods Depot (synthetic)", "Food Processing", "KKRI-0144", 22000.0),
    ("Krai Palm Oil Collection Centre (synthetic)", "Logistics", "KKRI-0145", 15000.0),
    ("Riverside Homestay Group (synthetic)", "Hotel", "KKRI-0146", 6500.0),
]


def _row(rng: random.Random, name: str, sector: str, tower: str, value: float | None = None) -> tuple[str, str, str, str, float, float, float]:
    monthly = value if value is not None else round(rng.uniform(*VALUE_RANGE) / 500) * 500.0
    return (name, sector, tower, rng.choice(PLANS), monthly, rng.choice(SLA_PCT), round(monthly * PENALTY_SHARE, 2))


def build_enterprise(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    rng = random.Random(f"{seed}:enterprise")
    rows: list[tuple[str, str, str, str, float, float, float]] = []
    seen: set[str] = set()

    def add(row: tuple[str, str, str, str, float, float, float]) -> None:
        if row[0] not in seen:
            seen.add(row[0])
            rows.append(row)

    for site in conn.execute("SELECT name, serving_enodeb FROM critical_site WHERE kind = 'ENTERPRISE' ORDER BY critical_site_id"):
        add(_row(rng, site[0], "Logistics", site[1]))
    for name, sector, tower, value in CLUSTER_ACCOUNTS:
        add(_row(rng, name, sector, tower, value))
    cluster = {t for _, _, t, _ in CLUSTER_ACCOUNTS}
    by_town: dict[str, list[TowerRow]] = {}
    for candidate in towers:
        if candidate.enodeb_name[:4] != "KKRI":
            by_town.setdefault(candidate.town, []).append(candidate)
    for town in sorted(by_town):
        for _ in range(PER_TOWN):
            sector = rng.choice(SECTORS)
            anchor = rng.choice(by_town[town])
            add(_row(rng, f"{town} {sector} Sdn Bhd (synthetic)", sector, anchor.enodeb_name))
    assert cluster <= {t.enodeb_name for t in towers}, "a cluster account names an unknown tower"
    conn.executemany(
        "INSERT INTO enterprise_account VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [(f"ACC-{i:04d}", *row) for i, row in enumerate(rows, start=1)],
    )