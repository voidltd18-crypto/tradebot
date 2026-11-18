"""Research-only technology swing strategy and conservative daily-bar backtest.

No broker imports, credentials, network calls, or order submission.
Live trading is NOT connected. Input must be historical daily OHLCV CSV.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from math import isfinite
import csv
import json
import sys

UNIVERSE = frozenset({"AAPL", "MSFT", "NVDA", "GOOG", "GOOGL", "AMZN", "META"})
STARTING_CASH = 10000.0
MAX_ALLOCATION = 0.25
MAX_HOLD_DAYS = 60  # trading sessions; roughly 12 weeks
MIN_HOLD_DAYS = 10
STOP_PCT = 0.08
TARGET_PCT = 0.18
FRICTION_BPS = 15  # each side; explicit synthetic spread/slippage assumption


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


def validate(bars):
    if len(bars) < 202:
        raise ValueError("Need >=202 daily bars to avoid trading on insufficient history")
    last = None
    for b in bars:
        if last is not None and b.day <= last:
            raise ValueError("Bars must be strictly ascending, unique trading dates")
        last = b.day
        if not all(isfinite(v) and v > 0 for v in (b.open, b.high, b.low, b.close, b.volume)):
            raise ValueError("Invalid OHLCV")
        if b.low > min(b.open, b.close) or b.high < max(b.open, b.close):
            raise ValueError("Inconsistent OHLC")


def mean(values):
    return sum(values) / len(values)


def signal(bars, i):
    """Use only fully completed bars up to i; no future leakage."""
    if i < 200:
        return False
    closes = [b.close for b in bars]
    c = closes[i]
    return (c > mean(closes[i-49:i+1]) > mean(closes[i-199:i+1])
            and c > closes[i-20] and bars[i].volume >= mean([b.volume for b in bars[i-19:i+1]]) * 0.7)


def backtest(symbol, bars, *, starting_cash=STARTING_CASH, friction_bps=FRICTION_BPS):
    if symbol not in UNIVERSE:
        raise ValueError("Symbol outside approved tech universe")
    validate(bars)
    if starting_cash <= 0 or friction_bps < 0 or friction_bps > 100:
        raise ValueError("Invalid capital or friction")
    cash, qty, entry, entry_i = float(starting_cash), 0.0, 0.0, -1
    trades = []
    equity_curve = []
    friction = friction_bps / 10000
    for i, bar in enumerate(bars):
        # Orders from prior close execute at today's open. Never same-bar signal/fill.
        if qty:
            hold = i - entry_i
            # Stops may gap through; fill at the worse of stop and open.
            stop = entry * (1 - STOP_PCT)
            target = entry * (1 + TARGET_PCT)
            exit_price = None
            reason = None
            if bar.low <= stop:
                exit_price, reason = min(bar.open, stop), "STOP"
            elif hold >= MIN_HOLD_DAYS and bar.high >= target:
                exit_price, reason = max(bar.open, target), "TARGET"
            elif hold >= MAX_HOLD_DAYS:
                exit_price, reason = bar.open, "TIME"
            elif hold >= MIN_HOLD_DAYS and i > 0 and bars[i-1].close < mean([b.close for b in bars[i-50:i]]):
                exit_price, reason = bar.open, "TREND"
            if exit_price is not None:
                proceeds = qty * exit_price * (1 - friction)
                cash += proceeds
                trades.append({"entryDay": bars[entry_i].day.isoformat(), "exitDay": bar.day.isoformat(),
                               "entry": round(entry, 4), "exit": round(exit_price, 4),
                               "pnl": round(proceeds - qty * entry, 2), "reason": reason})
                qty, entry, entry_i = 0.0, 0.0, -1
        if not qty and i > 200 and signal(bars, i-1):
            # One position, maximum 25% of total equity, with cash reserve.
            allocation = cash * MAX_ALLOCATION
            price = bar.open * (1 + friction)
            qty = allocation / price
            cash -= allocation
            entry, entry_i = price, i
        equity_curve.append(cash + qty * bar.close)
    final_equity = equity_curve[-1]
    peak, drawdown = equity_curve[0], 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return {"symbol": symbol, "readOnly": True, "ordersSubmitted": 0,
            "trades": trades, "closedTrades": len(trades),
            "finalEquity": round(final_equity, 2),
            "totalReturnPct": round(100 * (final_equity / starting_cash - 1), 2),
            "maxDrawdownPct": round(100 * drawdown, 2),
            "openPositionAtEnd": bool(qty),
            "assumptions": {"dailyBars": True, "nextOpenEntry": True,
                            "maxAllocationPct": 25, "stopPct": 8,
                            "targetPct": 18, "maxHoldTradingDays": 60,
                            "minHoldTradingDays": 10, "frictionBpsPerSide": friction_bps,
                            "dividendsAndTaxes": "excluded", "unfilledOrders": "not modelled"}}


def load_csv(path):
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [Bar(date.fromisoformat(row["date"]), *(float(row[key]) for key in ("open", "high", "low", "close", "volume"))) for row in reader]


def main(argv):
    if len(argv) != 3:
        raise SystemExit("Usage: python -m backend.v20_tech_swing_research SYMBOL daily_bars.csv")
    symbol, path = argv[1:]
    print(json.dumps(backtest(symbol.upper(), load_csv(path)), indent=2))


if __name__ == "__main__":
    main(sys.argv)
