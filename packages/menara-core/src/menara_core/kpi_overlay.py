"""Applied RAN changes modify tower KPIs. Readers of tower_kpi apply this overlay so effects are visible.

ran-mcp owns `ran_change` and `ran_kpi_effect`. Domains whose data those changes modify (tower, ontology)
read them read-only through this module; nothing calls ran-mcp.
"""

from __future__ import annotations

import sqlite3

_ACTIVE = (
    "SELECT e.prb_factor, e.drop_factor, e.thr_factor FROM ran_kpi_effect e "
    "JOIN ran_change c ON c.change_id = e.change_id "
    "WHERE e.enodeb_name = ? AND e.from_min <= ? AND (c.reverted_min IS NULL OR ? < c.reverted_min)"
)


def adjust(
    conn: sqlite3.Connection, enodeb_name: str, t_min: int, prb: float, drop: float, thr: float
) -> tuple[float, float, float]:
    """KPI sample (prb %, drop %, Mbps) at t_min after every active RAN change on the tower."""
    prb_f = drop_f = thr_f = 1.0
    for row in conn.execute(_ACTIVE, (enodeb_name, t_min, t_min)):
        prb_f *= row["prb_factor"]
        drop_f *= row["drop_factor"]
        thr_f *= row["thr_factor"]
    if prb_f == drop_f == thr_f == 1.0:
        return prb, drop, thr
    return round(min(100.0, prb * prb_f), 1), round(drop * drop_f, 2), round(thr * thr_f, 1)
