"""Experimental, read-only classification of stock exit momentum.

This module never submits an order or overrides existing stock stop losses.
It is intentionally NOT connected to the live trading loop.
"""
from dataclasses import dataclass
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class ExitSettings:
    spike_min_gain_pct: float = 2.0
    spike_trail_pct: float = 0.5
    trend_trail_pct: float = 0.7
    spike_window: int = 5
    spike_window_rise_pct: float = 1.5

    def __post_init__(self):
        values = (self.spike_min_gain_pct, self.spike_trail_pct,
                  self.trend_trail_pct, self.spike_window_rise_pct)
        if not all(isfinite(v) and v > 0 for v in values):
            raise ValueError("all percentage thresholds must be finite and positive")
        if self.spike_window < 2:
            raise ValueError("spike_window must be at least 2")


def assess_exit(
    entry_price: float,
    observed_prices: Sequence[float],
    *,
    settings: ExitSettings = ExitSettings(),
    enabled: bool = False,
) -> dict:
    """Produce a diagnostic only, never a sell order.

    Prices must be chronological, from a single position's observation period;
    peak is derived from the full supplied sequence, not just the spike window.
    Equal-spaced sampling must be verified by the eventual caller.
    """
    if not isfinite(entry_price) or entry_price <= 0:
        raise ValueError("entry_price must be finite and positive")
    if not observed_prices or any(not isfinite(p) or p <= 0 for p in observed_prices):
        raise ValueError("observed_prices must contain finite, positive prices")
    current = observed_prices[-1]
    peak = max(observed_prices)
    gain_pct = (current / entry_price - 1) * 100
    peak_gain_pct = (peak / entry_price - 1) * 100
    drawdown_pct = (1 - current / peak) * 100
    enough_samples = len(observed_prices) >= settings.spike_window
    window_rise_pct = ((current / observed_prices[-settings.spike_window] - 1) * 100
                       if enough_samples else None)
    fast_rise = enough_samples and window_rise_pct >= settings.spike_window_rise_pct
    mode = "SPIKE" if fast_rise else "TREND"
    threshold = settings.spike_trail_pct if mode == "SPIKE" else settings.trend_trail_pct

    # The spike activation requires an actual observed spike, not just a gain
    # relative to entry. Never request a loss-making 'profit protection' exit.
    armed = (peak_gain_pct >= settings.spike_min_gain_pct and
             gain_pct > 0 and enough_samples)
    candidate = armed and drawdown_pct >= threshold
    return {
        "enabled": bool(enabled),
        "readOnly": True,
        "mode": mode,
        "reason": ("disabled" if not enabled else
                   "insufficient_samples" if not enough_samples else
                   "below_activation_or_not_profitable" if not armed else
                   "peak_reversal" if candidate else "monitoring"),
        "profitPct": round(gain_pct, 4),
        "peakProfitPct": round(peak_gain_pct, 4),
        "peakDrawdownPct": round(drawdown_pct, 4),
        "windowRisePct": round(window_rise_pct, 4) if window_rise_pct is not None else None,
        "candidateExit": bool(enabled and candidate),
        "existingRiskControlsRequired": True,
    }
