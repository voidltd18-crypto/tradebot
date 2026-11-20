"""Offline walk-forward research metrics; no broker connection or orders.

Consumes externally sourced daily closes. Results are hypothetical fixed-horizon
signal returns, not an executable portfolio or evidence of live profitability.
"""
from dataclasses import dataclass
from datetime import date
from math import isfinite
from statistics import mean

from backend.tradebot_v2.engine import TECH_UNIVERSE, evaluate_pullback


@dataclass(frozen=True)
class DatedClose:
    day: date
    close: float


@dataclass(frozen=True)
class BacktestSummary:
    symbol: str
    source: str
    sample_start: date
    sample_end: date
    training_end: date
    test_signals: int
    net_mean_return_pct: float | None
    benchmark_return_pct: float
    worst_signal_drawdown_pct: float | None
    profitable_signals: int
    fee_bps_roundtrip: float
    warning: str = "Overlapping fixed-horizon signals; not portfolio P&L"


def evaluate_out_of_sample(
    symbol: str,
    rows: list[DatedClose],
    *,
    source: str,
    training_end: date,
    forward_bars: int = 5,
    roundtrip_fee_bps: float = 20.0,
) -> BacktestSummary:
    """Measure signals generated strictly from historical data available at each bar.

    A fixed pre-declared training cutoff separates test observations. Includes
    entry+exit fees but excludes spread, slippage and execution constraints.
    """
    if symbol not in TECH_UNIVERSE or not isinstance(source, str) or not source.strip():
        raise ValueError("Approved symbol and nonempty provenance required")
    if not isinstance(training_end, date) or isinstance(training_end, __import__("datetime").datetime):
        raise ValueError("Training cutoff must be a date")
    if not isinstance(forward_bars, int) or isinstance(forward_bars, bool) or forward_bars < 1:
        raise ValueError("Invalid horizon")
    if not isinstance(roundtrip_fee_bps, (int, float)) or not isfinite(roundtrip_fee_bps) or roundtrip_fee_bps < 0:
        raise ValueError("Invalid fee assumption")
    if len(rows) < 31 + forward_bars:
        raise ValueError("Insufficient historical prices")
    if any(not isinstance(r, DatedClose) or not isinstance(r.day, date)
           or isinstance(r.day, __import__("datetime").datetime)
           or not isinstance(r.close, (int, float))
           or not isfinite(r.close) or r.close <= 0 for r in rows):
        raise ValueError("Invalid daily closes")
    if any(rows[i].day >= rows[i + 1].day for i in range(len(rows) - 1)):
        raise ValueError("Dates must be strictly increasing")
    test_indices = [i for i, r in enumerate(rows) if r.day > training_end]
    if not test_indices or test_indices[0] < 30:
        raise ValueError("Training period too short or test period empty")
    closes = [r.close for r in rows]
    net_returns = []
    drawdowns = []
    for i in test_indices:
        if i + forward_bars >= len(rows):
            continue
        if evaluate_pullback(symbol, closes[:i + 1]).status != "GREEN":
            continue
        entry = closes[i]
        future = closes[i + 1:i + forward_bars + 1]
        net_returns.append((future[-1] / entry - 1) * 100 - roundtrip_fee_bps / 100)
        drawdowns.append((min(future) / entry - 1) * 100)
    start = test_indices[0]
    benchmark = (closes[-1] / closes[start] - 1) * 100
    return BacktestSummary(
        symbol=symbol, source=source.strip(), sample_start=rows[0].day,
        sample_end=rows[-1].day, training_end=training_end,
        test_signals=len(net_returns),
        net_mean_return_pct=round(mean(net_returns), 4) if net_returns else None,
        benchmark_return_pct=round(benchmark, 4),
        worst_signal_drawdown_pct=round(min(drawdowns), 4) if drawdowns else None,
        profitable_signals=sum(r > 0 for r in net_returns),
        fee_bps_roundtrip=float(roundtrip_fee_bps),
    )
