"""A deliberately simple network model shared by twin-mcp (prediction) and ran-mcp (realised effect).

These are demo formulas, not RF engineering. Tuned so a 4 degree downtilt takes an overloaded
neighbour from 91 % to about 63 % PRB utilisation.
"""

from __future__ import annotations

OVERLOAD_PRB = 85.0
LOAD_REDUCTION_PER_DEG = 0.077
MAX_LOAD_REDUCTION = 0.4
COVERAGE_LOSS_PER_DEG_PCT = 3.5
MAX_COVERAGE_LOSS_PCT = 15.0
MAX_TILT_DELTA_DEG = 8.0
FACTOR_MIN, FACTOR_MAX = 0.5, 1.5
FAILOVER_SHARE = 0.6  # share of a failed tower's load that moves to neighbours
FAILOVER_GAIN = 2.0  # neighbours absorb it at roughly half the efficiency (overlapping coverage)
OFFLOAD_SPILL = 0.5  # share of load shed by a downtilt that lands on neighbours; the rest is handed over


def load_reduction(delta_deg: float) -> float:
    """Fraction of a tower's load removed by tilting `delta_deg` down (negative = uptilt, adds load)."""
    return max(-MAX_LOAD_REDUCTION, min(MAX_LOAD_REDUCTION, delta_deg * LOAD_REDUCTION_PER_DEG))


def coverage_loss_pct(delta_deg: float) -> float:
    """Share of the cell's coverage area given up by a downtilt (uptilt loses none)."""
    return round(max(0.0, delta_deg) * COVERAGE_LOSS_PER_DEG_PCT, 1)


def predicted_prb(current_prb: float, delta_deg: float) -> float:
    return round(max(0.0, min(100.0, current_prb * (1 - load_reduction(delta_deg)))), 1)


def _clamp(value: float) -> float:
    return max(FACTOR_MIN, min(FACTOR_MAX, value))


def effect_factors(delta_deg: float, efficacy: float = 1.0) -> tuple[float, float, float]:
    """(prb, drop_rate, throughput) multipliers a tilt really causes. efficacy scales the effect."""
    reduction = load_reduction(delta_deg) * max(0.0, min(1.0, efficacy))
    return (
        round(_clamp(1 - reduction), 4),
        round(_clamp(1 - 0.8 * reduction), 4),
        round(_clamp(1 + 0.5 * reduction), 4),
    )