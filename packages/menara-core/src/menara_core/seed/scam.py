"""Synthetic scam signals: ten generic patterns, and hourly counts of reports and blocked attempts per town.

Counts only: nothing here identifies a person, a number, a sender or a message. The patterns are generic ("a fake
parcel message") with no real brand, link or number. Most patterns run at a steady rate; three rise in a few towns,
and a fake flood-relief donation message surges in the flood region (Kelantan) around T0. Own random stream.
"""

from __future__ import annotations

import math
import random
import sqlite3

from menara_core.seed.towers import TowerRow

PERIOD = (-1440, 720)
STEP_MIN = 60
ADVICE = "Do not open links or share a code. Check with the organisation through its official app or website."
FLOOD_STATE = "Kelantan"
BLOCK_RATIO = 3.5  # blocked attempts per report
SPIKE_TOWNS = 3

# (name, kind, severity, example, base reports per hour in a typical town)
PATTERNS: list[tuple[str, str, str, str, float]] = [
    ("Fake parcel delivery message (synthetic)", "SMS", "MEDIUM", "A message says a parcel is held and asks for a small fee to release it.", 3.0),
    ("Fake bank officer call (synthetic)", "VOICE", "HIGH", "A caller says an account is frozen and asks you to move money to a 'safe account'.", 1.8),
    ("Prize or lucky draw message (synthetic)", "MESSAGING", "LOW", "A message says you won a prize and asks you to reply with personal details.", 2.2),
    ("Easy online job offer (synthetic)", "MESSAGING", "MEDIUM", "A message offers high pay for simple online tasks, after a small deposit.", 2.0),
    ("Investment tip group (synthetic)", "MESSAGING", "HIGH", "You are added to a group promising guaranteed returns on a trading tip.", 1.2),
    ("Fake utility disconnection message (synthetic)", "SMS", "MEDIUM", "A message says power or water will be cut today unless a bill is paid now.", 1.6),
    ("Fake authority call (synthetic)", "VOICE", "HIGH", "A caller claims to be an officer and says you are linked to a case.", 1.0),
    ("Romance and gift scam (synthetic)", "MESSAGING", "MEDIUM", "A new online friend asks for money to cover a gift or a ticket.", 0.8),
    ("Fake flood-relief donation request (synthetic)", "SMS", "HIGH", "A message asks you to donate to a flood victims fund through an unknown account.", 0.3),
    ("Fake mobile plan upgrade message (synthetic)", "SMS", "MEDIUM", "A message says your SIM must be upgraded today and asks you to confirm details.", 1.4),
]


def build_scam(conn: sqlite3.Connection, seed: int, towers: list[TowerRow]) -> None:
    rng = random.Random(f"{seed}:scam")
    conn.executemany(
        "INSERT INTO scam_pattern VALUES (?, ?, ?, ?, ?, ?)",
        [(f"SCM-{i:02d}", name, kind, severity, example, ADVICE) for i, (name, kind, severity, example, _) in enumerate(PATTERNS, start=1)],
    )
    state_of: dict[str, str] = {}
    for t in towers:
        state_of.setdefault(t.town, t.state)
    towns = sorted(state_of)
    town_factor = {town: rng.uniform(0.5, 1.6) for town in towns}
    spikes = {i: set(rng.sample(towns, min(SPIKE_TOWNS, len(towns)))) for i in (1, 2, 4)}  # pattern index -> towns where it surges
    times = range(PERIOD[0], PERIOD[1] + 1, STEP_MIN)
    rows: list[tuple[str, str, int, int, int]] = []
    for index, (_, _, _, _, base) in enumerate(PATTERNS, start=1):
        pattern_id = f"SCM-{index:02d}"
        for town in towns:
            for minute in times:
                daily = 1.0 + 0.25 * math.sin((minute + 420) / 1440.0 * 2 * math.pi)
                rate = base * town_factor[town] * daily
                bump = math.exp(-((minute / 180.0) ** 2))
                if state_of[town] == FLOOD_STATE and pattern_id == "SCM-09":
                    rate += 9.0 * bump
                if town in spikes.get(index, set()):
                    rate += base * 3.0 * bump
                reports = max(0, round(rate + rng.uniform(-0.6, 0.6) * max(rate, 1.0)))
                blocked = max(0, round(reports * BLOCK_RATIO * rng.uniform(0.8, 1.2)))
                rows.append((pattern_id, town, minute, reports, blocked))
    conn.executemany("INSERT INTO scam_signal VALUES (?, ?, ?, ?, ?)", rows)