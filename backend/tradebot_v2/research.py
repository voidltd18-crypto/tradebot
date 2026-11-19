"""Read-only historical signal evaluation; no trades or simulated fills.

Walk-forward signals use only prices known as of each evaluation date.
Results measure signal frequency and forward price changes, NOT trading returns.
"""
from dataclasses import dataclass
from statistics import mean
from math import isfinite

from backend.tradebot_v2.engine import evaluate_pullback


@dataclass(frozen=True)
class ResearchStats:
    symbol: str
    observations: int
    green_signals: int
    evaluated_signals: int
    positive_after_5_bars: int
    average_forward_5_bar_pct: float | None


def evaluate_history(symbol: str, closes: list[float], forward_bars: int = 5) -> ResearchStats:
    if forward_bars < 1:
        raise ValueError("forward_bars must be positive")
    if any(not isinstance(v, (int, float)) or not isfinite(v) or v <= 0 for v in closes):
        raise ValueError("Prices must be positive numbers")
    green = 0
    forward = []
    # Never look at the future when generating a signal.
    for i in range(29, len(closes)):
        signal = evaluate_pullback(symbol, closes[:i + 1])
        if signal.status != "GREEN":
            continue
        green += 1
        if i + forward_bars < len(closes):
            forward.append((closes[i + forward_bars] / closes[i] - 1) * 100)
    return ResearchStats(
        symbol=symbol,
        observations=max(0, len(closes) - 29),
        green_signals=green,
        evaluated_signals=len(forward),
        positive_after_5_bars=sum(x > 0 for x in forward),
        average_forward_5_bar_pct=round(mean(forward), 3) if forward else None,
    )
