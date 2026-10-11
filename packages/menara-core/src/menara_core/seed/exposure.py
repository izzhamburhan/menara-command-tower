"""Synthetic network-exposure products: quality on demand, sold per tower per hour. Invented prices and capacity.

Four profiles in `qod_profile`, read by exposure-mcp. `headroom_prb` is the share of a tower's radio capacity (PRB
points) that a booking reserves; a tower needs that much spare capacity, plus a safety margin, to be sold. Nothing here
describes a real product, price or service.
"""

from __future__ import annotations

import sqlite3

PROFILES: list[tuple[str, str, str, str, float, float]] = [
    ("AR_EXPERIENCE", "Immersive experience", "Synthetic product: high downlink for AR and live-venue apps.", "50 Mbps downlink per user", 15.0, 300.0),
    ("BROADCAST_UPLINK", "Broadcast uplink", "Synthetic product: guaranteed uplink for media crews at a crowded venue.", "25 Mbps uplink per crew", 12.0, 450.0),
    ("ESPORTS_LOW_LATENCY", "Low-latency gaming", "Synthetic product: low latency for a gaming or esports event.", "under 30 ms latency", 8.0, 220.0),
    ("FLEET_TELEMATICS", "Fleet telematics", "Synthetic product: steady connectivity for a delivery or ride fleet.", "2 Mbps per vehicle", 4.0, 90.0),
]


def build_exposure(conn: sqlite3.Connection) -> None:
    conn.executemany("INSERT INTO qod_profile VALUES (?, ?, ?, ?, ?, ?)", PROFILES)