"""Bianchi-style saturated DCF fixed-point collision probabilities.

Bianchi's idealized infinite-retry capped-stage model is reported alongside a
finite retry (0..7) renewal-cycle correction matching the experiment rule.
Both use decoupled, constant per-attempt collision probability assumptions.
"""
from __future__ import annotations

from scipy.optimize import brentq


def cw_values(cw_min: int = 15, cw_max: int = 1023) -> list[int]:
    stages = [cw_min]
    while stages[-1] < cw_max:
        stages.append(min(2 * (stages[-1] + 1) - 1, cw_max))
    return stages


def attempt_probability(p: float, retry_limit: int | None = None,
                        cw_min: int = 15, cw_max: int = 1023) -> float:
    """tau(p) via average attempts / average virtual backoff slots.

    CW is *maximum inclusive backoff*; virtual attempt-stage residence is
    (CW + 2)/2 slots. Infinite retry remains in the terminal CW stage.
    """
    stages = cw_values(cw_min, cw_max)
    if retry_limit is None:
        weights = [p ** k for k in range(len(stages) - 1)]
        weights.append(p ** (len(stages) - 1) / (1 - p))
        windows = stages
    else:
        weights = [p ** k for k in range(retry_limit + 1)]
        windows = [stages[min(k, len(stages) - 1)] for k in range(retry_limit + 1)]
    attempts = sum(weights)
    lifetime = sum(weight * (cw + 2) / 2
                   for weight, cw in zip(weights, windows))
    return attempts / lifetime


def collision_probability(stations: int, retry_limit: int | None = None,
                          cw_min: int = 15, cw_max: int = 1023) -> float:
    if stations <= 1:
        return 0.0

    def residual(p: float) -> float:
        tau = attempt_probability(p, retry_limit, cw_min, cw_max)
        return p - (1 - (1 - tau) ** (stations - 1))

    return float(brentq(residual, 1e-12, 1 - 1e-12, xtol=1e-13))
