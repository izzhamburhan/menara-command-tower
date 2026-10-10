"""Synthetic subscribers, their experience, and tickets (baseline noise plus the Kuala Krai storm)."""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from menara_core.geo import haversine_km
from menara_core.privacy import coarsen_location, hash_msisdn
from menara_core.scenario import Scenario
from menara_core.seed.towers import TowerRow

PLAN = "UniFi Mobile"
BAND_WEIGHTS = [5, 3, 2]
EXPERIENCE_STEP_MIN = 120
STORM_STEP_MIN = 5
EXPERIENCE_START, EXPERIENCE_END = -1440, 480
STORM_START, STORM_END = -60, 480
BASELINE_TICKET_FIRST_ID = 70000
CATEGORIES = ["No data", "Slow data", "No signal", "Call drop", "Indoor coverage"]
BASELINE_STATUSES = ["OPEN", "IN_PROGRESS", "RESOLVED"]
SERVICE = "UniFi Mobile"
GEOCODE_JITTER_KM = 1.0


@dataclass(frozen=True)
class Sub:
    msisdn_hash: str
    serving_cell: str
    enodeb_name: str


def _synthetic_msisdn(rng: random.Random) -> str:
    return f"+601{rng.randint(0, 9)}{rng.randint(0, 99_999_999):08d}"


def _experience(rng: random.Random, kpi: tuple[float, float, float]) -> tuple[float, float, int, int]:
    """(score 0-100, throughput Mbps, drop events, rsrp dBm) for one subscriber given tower KPIs."""
    prb, drop, thr = kpi
    if thr <= 0.0 and prb <= 0.0:
        return 0.0, 0.0, 0, -140
    sub_thr = thr * rng.uniform(0.4, 1.1)
    score = max(0.0, min(100.0, 100 * min(1.0, sub_thr / 30.0) - drop * 5))
    return round(score, 1), round(sub_thr, 1), int(drop * rng.uniform(0, 2)), rng.randint(-110, -80)


def _geocode(rng: random.Random, lat: float, lng: float) -> tuple[float, float]:
    d = GEOCODE_JITTER_KM / 111.0
    return round(lat + rng.uniform(-d, d), 5), round(lng + rng.uniform(-d, d), 5)


def _make_subscribers(
    conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow]
) -> dict[str, list[Sub]]:
    cluster_names = {t.enodeb for t in scenario.cluster.towers}
    by_tower: dict[str, list[Sub]] = {}
    seen: set[str] = set()
    rows: list[tuple[object, ...]] = []
    for tower in towers:
        count = scenario.tickets.subscribers_per_tower if tower.enodeb_name in cluster_names else rng.randint(6, 14)
        cells = [r[0] for r in conn.execute("SELECT cell_id FROM cell WHERE enodeb_name = ? ORDER BY cell_id", (tower.enodeb_name,))]
        cell_lat, cell_lng = coarsen_location(tower.lat, tower.lng)
        subs: list[Sub] = []
        for index in range(count):
            digest = hash_msisdn(_synthetic_msisdn(rng))
            while digest in seen:
                digest = hash_msisdn(_synthetic_msisdn(rng))
            seen.add(digest)
            serving = cells[0] if (index == 0 and tower.enodeb_name == scenario.tickets.hub) else rng.choices(cells, BAND_WEIGHTS[: len(cells)])[0]
            subs.append(Sub(digest, serving, tower.enodeb_name))
            rows.append(
                (digest, serving, tower.enodeb_name, cell_lat, cell_lng, PLAN,
                 "postpaid" if rng.random() < 0.6 else "prepaid", int(rng.random() < 0.35))
            )
        by_tower[tower.enodeb_name] = subs
    conn.executemany("INSERT INTO subscriber VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return by_tower


def _make_state_and_experience(
    conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, by_tower: dict[str, list[Sub]]
) -> None:
    kpi = {
        (r[0], r[1]): (r[2], r[3], r[4])
        for r in conn.execute("SELECT enodeb_name, t_min, prb_util, drop_rate, throughput_mbps FROM tower_kpi")
    }
    states: dict[str, list[tuple[int, str]]] = {}
    for name, t_min, status in conn.execute("SELECT enodeb_name, t_min, status FROM tower_state ORDER BY enodeb_name, t_min"):
        states.setdefault(name, []).append((t_min, status))
    cluster_names = {t.enodeb for t in scenario.cluster.towers}
    grid = list(range(EXPERIENCE_START, EXPERIENCE_END + 1, EXPERIENCE_STEP_MIN))
    storm_grid = [*range(EXPERIENCE_START, STORM_START, EXPERIENCE_STEP_MIN // 2), *range(STORM_START, STORM_END + 1, STORM_STEP_MIN)]
    for name, subs in by_tower.items():
        previous: bool | None = None
        for t_min, status in states.get(name, []):
            attached = status != "DOWN"
            if attached != previous:
                conn.executemany("INSERT INTO subscriber_state VALUES (?, ?, ?)", [(s.msisdn_hash, t_min, int(attached)) for s in subs])
                previous = attached
        times = storm_grid if name in cluster_names else grid
        exp_rows = [
            (s.msisdn_hash, t, *_experience(rng, kpi[(name, t)]))
            for s in subs
            for t in times
            if (name, t) in kpi
        ]
        conn.executemany("INSERT INTO subscriber_experience VALUES (?, ?, ?, ?, ?, ?)", exp_rows)


def _insert_ticket(
    conn: sqlite3.Connection, rng: random.Random, ticket_id: str, created_min: int, category: str,
    status: str, location_text: str, lat: float, lng: float, customer: str, summary: str, language: str,
) -> None:
    glat, glng = _geocode(rng, lat, lng)
    conn.execute(
        "INSERT INTO ticket VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ticket_id, created_min, SERVICE, category, status, location_text, glat, glng, customer, summary, language),
    )


def _make_tickets(
    conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow], by_tower: dict[str, list[Sub]]
) -> None:
    storm = scenario.tickets
    positions = {t.enodeb_name: t for t in towers}
    cluster_names = {t.enodeb for t in scenario.cluster.towers}

    baseline = [t for t in towers if t.enodeb_name not in cluster_names]
    for index in range(max(1, len(baseline) // 5)):
        tower = rng.choice(baseline)
        sub = rng.choice(by_tower[tower.enodeb_name])
        _insert_ticket(
            conn, rng, f"TK-{BASELINE_TICKET_FIRST_ID + index}", rng.randint(-1440, 0), rng.choice(CATEGORIES),
            rng.choice(BASELINE_STATUSES), tower.town, tower.lat, tower.lng, sub.msisdn_hash,
            "Data is slow in my area", "en",
        )
    prior = BASELINE_TICKET_FIRST_ID + len(baseline) // 5
    hub = positions[storm.hub]
    for offset in range(3):
        sub = by_tower[storm.hub][offset + 1]
        _insert_ticket(
            conn, rng, f"TK-{prior + offset}", -1000 + offset * 100, "Slow data", "RESOLVED",
            scenario.cluster.town, hub.lat, hub.lng, sub.msisdn_hash, "Slow data in the evening", "en",
        )

    near = [
        name for name in cluster_names
        if haversine_km(hub.lat, hub.lng, positions[name].lat, positions[name].lng) <= storm.max_distance_km
    ]
    hub_subs = by_tower[storm.hub]
    other_subs = sorted((s for name in near if name != storm.hub for s in by_tower[name]), key=lambda s: s.msisdn_hash)
    hub_count = round(storm.count * storm.hub_share)
    chosen = [*hub_subs[:1], *rng.sample(hub_subs[1:], hub_count - 1), *rng.sample(other_subs, storm.count - hub_count)]
    times = [0, *sorted(rng.randint(1, storm.window_min) for _ in range(storm.count - 1))]
    for index, (sub, t_min) in enumerate(zip(chosen, times, strict=True)):
        tower = positions[sub.enodeb_name]
        first = index == 0
        _insert_ticket(
            conn, rng, f"TK-{storm.first_id + index}", t_min, "No data", "OPEN",
            storm.localities[0] if first else rng.choice(storm.localities), tower.lat, tower.lng,
            sub.msisdn_hash, storm.first_summary if first else rng.choice(storm.summaries), "ms" if first else rng.choice(["ms", "en"]),
        )


def build_people(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario, towers: list[TowerRow]) -> None:
    by_tower = _make_subscribers(conn, rng, scenario, towers)
    _make_state_and_experience(conn, rng, scenario, by_tower)
    _make_tickets(conn, rng, scenario, towers, by_tower)
