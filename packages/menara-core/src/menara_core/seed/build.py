"""Build menara.db: baseline towers across Malaysia plus the scripted Kuala Krai flood cluster."""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

from menara_core.scenario import Scenario
from menara_core.seed import towers as gen
from menara_core.seed.actions import build_actions
from menara_core.seed.care import build_care
from menara_core.seed.context import build_context
from menara_core.seed.energy import build_energy
from menara_core.seed.enterprise import build_enterprise
from menara_core.seed.events import build_events
from menara_core.seed.exposure import build_exposure
from menara_core.seed.field import build_field
from menara_core.seed.movement import build_movement
from menara_core.seed.people import build_people
from menara_core.seed.schema import SCHEMA
from menara_core.seed.sites import build_malls, build_sites
from menara_core.seed.usage import build_usage

DEFAULT_TOWER_COUNT = 1200
DEFAULT_SEED = 42
BASELINE_T_MIN = -1440


def _remove_existing(db_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{db_path}{suffix}")
        try:
            target.unlink(missing_ok=True)
        except PermissionError as exc:
            raise SystemExit(f"Cannot replace {target}: stop every running MCP server first.") from exc


def _insert_towers(conn: sqlite3.Connection, rows: list[gen.TowerRow]) -> None:
    conn.executemany(
        "INSERT INTO tower VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (r.enodeb_name, r.site_id, r.name, r.town, r.state, r.lat, r.lng, r.tower_type, r.vendor, r.firmware)
            for r in rows
        ],
    )


def _baseline_tower(
    conn: sqlite3.Connection, rng: random.Random, row: gen.TowerRow, alarm_seq: int
) -> int:
    """Most towers are UP; a few are DEGRADED or DOWN with a matching alarm. Returns next alarm id."""
    roll = rng.random()
    status = "UP" if roll < 0.95 else ("DEGRADED" if roll < 0.985 else "DOWN")
    conn.execute(
        "INSERT INTO tower_state VALUES (?, ?, 'UP', 100, 1)", (row.enodeb_name, BASELINE_T_MIN)
    )
    down_from: int | None = None
    if status != "UP":
        code, severity, message = rng.choice(gen.BASELINE_ALARMS)
        if status == "DOWN":
            code, severity, message = gen.BASELINE_ALARMS[0]
        raised = rng.randint(-600, -10)
        down_from = raised if status == "DOWN" else None
        conn.execute(
            "INSERT INTO tower_state VALUES (?, ?, ?, ?, 1)",
            (row.enodeb_name, raised, status, rng.randint(80, 100)),
        )
        conn.execute(
            "INSERT INTO tower_alarm VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (f"ALM-{alarm_seq:06d}", row.enodeb_name, code, severity, message, raised),
        )
        alarm_seq += 1
    base = (rng.uniform(25, 70), rng.uniform(0.3, 1.2), rng.uniform(35, 90))
    for t_min in range(gen.KPI_HOURLY_START, gen.KPI_END_MIN + 1, 60):
        if down_from is not None and t_min >= down_from:
            sample = (0.0, 0.0, 0.0)
        else:
            sample = gen.diurnal_kpi(rng, t_min, base)
        conn.execute("INSERT INTO tower_kpi VALUES (?, ?, ?, ?, ?)", (row.enodeb_name, t_min, *sample))
    return alarm_seq


def _scripted_cluster(conn: sqlite3.Connection, rng: random.Random, scenario: Scenario) -> None:
    baseline = scenario.baseline_kpi
    base = (baseline.prb_util, baseline.drop_rate, baseline.throughput_mbps)
    for tower in scenario.cluster.towers:
        name = tower.enodeb
        conn.execute("INSERT INTO tower_state VALUES (?, ?, 'UP', 100, 1)", (name, BASELINE_T_MIN))
        steps = [*range(gen.KPI_HOURLY_START, -60, 60), *range(-60, gen.KPI_END_MIN + 1, 5)]
        for t_min in steps:
            profile = gen.profile_at(scenario.kpi_profiles, name, t_min)
            sample = (
                (profile.prb_util, profile.drop_rate, profile.throughput_mbps)
                if profile
                else gen.diurnal_kpi(rng, t_min, base)
            )
            conn.execute("INSERT INTO tower_kpi VALUES (?, ?, ?, ?, ?)", (name, t_min, *sample))
    for event in scenario.state_events:
        conn.execute(
            "INSERT INTO tower_state VALUES (?, ?, ?, ?, ?)",
            (event.tower, event.t_min, event.status, event.battery_pct, int(event.mains_ok)),
        )
    for alarm in scenario.alarm_events:
        conn.execute(
            "INSERT INTO tower_alarm VALUES (?, ?, ?, ?, ?, ?, ?)",
            (alarm.id, alarm.tower, alarm.code, alarm.severity, alarm.message, alarm.raised_min, alarm.cleared_min),
        )


def build(
    db_path: Path,
    scenario: Scenario,
    *,
    towers: int = DEFAULT_TOWER_COUNT,
    seed: int = DEFAULT_SEED,
) -> dict[str, int]:
    """Create a fresh database. Returns row counts for the seed summary."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_existing(db_path)
    rng = random.Random(seed)

    baseline = gen.generate_towers(rng, towers)
    cluster = gen.cluster_towers(scenario, rng)
    everything = [*baseline, *cluster]

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO seed_meta VALUES (?, ?)",
            [
                ("seed", str(seed)),
                ("scenario", scenario.name),
                ("scenario_start", scenario.start),
                ("synthetic", "true"),
            ],
        )
        conn.execute("INSERT INTO scenario_state VALUES (1, ?)", (scenario.default_now_min,))
        _insert_towers(conn, everything)
        for row in everything:
            conn.executemany("INSERT INTO cell VALUES (?, ?, ?, ?, ?)", gen.cells_for(rng, row))
        conn.executemany("INSERT INTO tower_neighbour VALUES (?, ?, ?)", gen.neighbours(everything))
        alarm_seq = 1
        for row in baseline:
            alarm_seq = _baseline_tower(conn, rng, row, alarm_seq)
        _scripted_cluster(conn, rng, scenario)
        build_people(conn, rng, scenario, everything)
        build_context(conn, rng, scenario, everything)
        build_sites(conn, rng, scenario, everything)
        build_malls(conn, seed, scenario, everything)  # own random stream
        build_usage(conn, seed, everything)  # own random stream
        build_field(conn, seed, scenario)  # own random stream
        build_exposure(conn)  # own random stream
        build_events(conn, seed, everything)  # own random stream
        build_enterprise(conn, seed, everything)  # own random stream
        build_care(conn, seed, everything)  # own random stream
        build_energy(conn, seed, everything)  # own random stream
        build_actions(conn, rng, scenario, everything)
        build_movement(conn, seed, scenario)  # last, with its own random stream, so older tables are unchanged
        conn.commit()
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in (
                "tower", "cell", "tower_neighbour", "tower_state", "tower_kpi", "tower_alarm",
                "subscriber", "subscriber_state", "subscriber_experience", "subscriber_cell_visit", "ticket",
                "weather_station", "weather_obs", "grid_feeder", "grid_feeder_tower", "grid_feeder_state",
                "flood_gauge", "flood_reading", "flood_extent", "critical_site", "tower_subscribers",
                "policy_setting", "ran_script", "drone", "drone_finding", "app", "app_hour_factor", "tower_app_share", "field_job", "spare_part", "technician", "qod_booking", "qod_profile", "crowd_event", "sla_credit", "enterprise_account", "care_notice", "care_language_mix", "care_template",
                "policy_setting", "ran_script", "drone", "drone_finding", "app", "app_hour_factor", "tower_app_share", "energy_action", "tower_energy",
            )
        }
    finally:
        conn.close()
    return counts