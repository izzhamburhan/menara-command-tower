"""Synthetic tower, cell, neighbour, state, KPI and alarm generators (pure functions, seeded RNG)."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from menara_core.geo import haversine_km
from menara_core.ids import cell_id_for, site_id_for
from menara_core.scenario import KpiProfile, Scenario

# (area code, town, state, lat, lng, weight, radius_km). Town centres are approximate.
TOWNS: list[tuple[str, str, str, float, float, int, float]] = [
    ("KULP", "Kuala Lumpur", "Wilayah Persekutuan", 3.1390, 101.6869, 10, 12),
    ("SHAH", "Shah Alam", "Selangor", 3.0738, 101.5183, 5, 10),
    ("PJYA", "Putrajaya", "Wilayah Persekutuan", 2.9264, 101.6964, 2, 6),
    ("GTWN", "George Town", "Pulau Pinang", 5.4141, 100.3288, 5, 8),
    ("IPOH", "Ipoh", "Perak", 4.5975, 101.0901, 4, 10),
    ("TPNG", "Taiping", "Perak", 4.8500, 100.7333, 2, 8),
    ("JBHR", "Johor Bahru", "Johor", 1.4927, 103.7414, 6, 12),
    ("BTPH", "Batu Pahat", "Johor", 1.8500, 102.9333, 2, 8),
    ("KLNG", "Kluang", "Johor", 2.0300, 103.3200, 2, 8),
    ("MLKA", "Melaka", "Melaka", 2.1896, 102.2501, 3, 8),
    ("SRMB", "Seremban", "Negeri Sembilan", 2.7258, 101.9424, 3, 8),
    ("KUAN", "Kuantan", "Pahang", 3.8077, 103.3260, 3, 10),
    ("TMLH", "Temerloh", "Pahang", 3.4500, 102.4167, 2, 8),
    ("KTRG", "Kuala Terengganu", "Terengganu", 5.3296, 103.1370, 3, 9),
    ("KTBH", "Kota Bharu", "Kelantan", 6.1254, 102.2381, 3, 9),
    ("GMSG", "Gua Musang", "Kelantan", 4.8820, 101.9650, 1, 12),
    ("TNMH", "Tanah Merah", "Kelantan", 5.8000, 102.1500, 1, 8),
    ("ASTR", "Alor Setar", "Kedah", 6.1248, 100.3678, 3, 9),
    ("KNGR", "Kangar", "Perlis", 6.4414, 100.1986, 1, 6),
    ("KCHG", "Kuching", "Sarawak", 1.5535, 110.3593, 4, 10),
    ("MIRI", "Miri", "Sarawak", 4.3995, 113.9914, 2, 8),
    ("SIBU", "Sibu", "Sarawak", 2.2870, 111.8300, 2, 8),
    ("KKIN", "Kota Kinabalu", "Sabah", 5.9804, 116.0735, 4, 10),
    ("SDKN", "Sandakan", "Sabah", 5.8394, 118.1172, 2, 8),
    ("TAWU", "Tawau", "Sabah", 4.2448, 117.8912, 2, 8),
    ("LABN", "Labuan", "Wilayah Persekutuan", 5.2831, 115.2308, 1, 5),
]
URBAN_CODES = {"KULP", "SHAH", "GTWN", "JBHR", "KKIN", "KCHG", "IPOH"}
VENDORS = ["Vendor-A", "Vendor-B", "Vendor-C"]
FIRMWARE = ["fw-4.1.0", "fw-4.2.1", "fw-4.2.2", "fw-5.0.0"]
BANDS = ["B1", "B3", "B7"]
BASELINE_ALARMS = [
    ("LINK_DOWN", "CRITICAL", "Backhaul link down"),
    ("CELL_HUNG", "MAJOR", "Cell not carrying traffic; reset required"),
    ("HIGH_TEMP", "MINOR", "Cabinet temperature above threshold"),
    ("VSWR", "MINOR", "Antenna VSWR above threshold"),
]
NEIGHBOUR_COUNT = 4
KPI_HOURLY_START, KPI_END_MIN = -1440, 480


@dataclass(frozen=True)
class TowerRow:
    enodeb_name: str
    site_id: str
    name: str
    town: str
    state: str
    lat: float
    lng: float
    tower_type: str
    vendor: str
    firmware: str


def _jitter(rng: random.Random, lat: float, lng: float, radius_km: float) -> tuple[float, float]:
    distance = radius_km * math.sqrt(rng.random())
    angle = rng.random() * 2 * math.pi
    dlat = (distance * math.cos(angle)) / 111.0
    dlng = (distance * math.sin(angle)) / (111.0 * math.cos(math.radians(lat)))
    return round(lat + dlat, 5), round(lng + dlng, 5)


def _tower_type(rng: random.Random, code: str) -> str:
    roll = rng.random()
    if code in URBAN_CODES:
        return "rooftop" if roll < 0.45 else "macro"
    return "pole" if roll < 0.05 else ("rooftop" if roll < 0.2 else "macro")


def generate_towers(rng: random.Random, count: int) -> list[TowerRow]:
    total_weight = sum(town[5] for town in TOWNS)
    rows: list[TowerRow] = []
    for code, town, state, lat, lng, weight, radius in TOWNS:
        for n in range(1, max(1, round(count * weight / total_weight)) + 1):
            tlat, tlng = _jitter(rng, lat, lng, radius)
            name = f"{code}-{n:04d}"
            rows.append(
                TowerRow(
                    enodeb_name=name,
                    site_id=site_id_for(name),
                    name=f"{town} Site {n:03d} (synthetic)",
                    town=town,
                    state=state,
                    lat=tlat,
                    lng=tlng,
                    tower_type=_tower_type(rng, code),
                    vendor=rng.choice(VENDORS),
                    firmware=rng.choice(FIRMWARE),
                )
            )
    return rows


def cluster_towers(scenario: Scenario, rng: random.Random) -> list[TowerRow]:
    cluster = scenario.cluster
    return [
        TowerRow(
            enodeb_name=t.enodeb,
            site_id=site_id_for(t.enodeb),
            name=f"{cluster.town} Site {t.enodeb[-3:]} (synthetic)",
            town=cluster.town,
            state=cluster.state,
            lat=t.lat,
            lng=t.lng,
            tower_type="macro",
            vendor=rng.choice(VENDORS),
            firmware=rng.choice(FIRMWARE),
        )
        for t in cluster.towers
    ]


def cells_for(rng: random.Random, tower: TowerRow) -> list[tuple[str, str, str, int, float]]:
    bands = BANDS if tower.tower_type == "macro" else BANDS[:2]
    return [
        (cell_id_for(tower.enodeb_name, band), tower.enodeb_name, band, rng.choice([0, 120, 240]), round(rng.uniform(3, 9), 1))
        for band in bands
    ]


def neighbours(towers: list[TowerRow]) -> list[tuple[str, str, float]]:
    pairs: list[tuple[str, str, float]] = []
    for tower in towers:
        scored = sorted(
            
                (haversine_km(tower.lat, tower.lng, other.lat, other.lng), other.enodeb_name)
                for other in towers
                if other.enodeb_name != tower.enodeb_name
            
        )
        pairs.extend((tower.enodeb_name, name, round(dist, 3)) for dist, name in scored[:NEIGHBOUR_COUNT])
    return pairs


def diurnal_kpi(rng: random.Random, t_min: int, base: tuple[float, float, float]) -> tuple[float, float, float]:
    """Hourly-ish KPI sample with a daily load curve peaking in the evening. Scenario T0 is 07:00."""
    hour = ((7 * 60 + t_min) / 60) % 24
    load = 1 + 0.35 * math.sin((hour - 13) / 24 * 2 * math.pi)
    prb = max(1.0, min(99.0, base[0] * load + rng.uniform(-4, 4)))
    drop = max(0.0, base[1] * (1 + (prb - base[0]) / 100) + rng.uniform(-0.15, 0.15))
    thr = max(0.0, base[2] * (1.1 - prb / 200) + rng.uniform(-3, 3))
    return round(prb, 1), round(drop, 2), round(thr, 1)


def profile_at(profiles: list[KpiProfile], tower: str, t_min: int) -> KpiProfile | None:
    eligible = [p for p in profiles if p.tower == tower and p.from_min <= t_min]
    return max(eligible, key=lambda p: p.from_min) if eligible else None