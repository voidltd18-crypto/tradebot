"""Offline research evaluation using public adjusted daily price history.

Research only; never imports Alpaca or sends orders.
Requires: pip install yfinance pandas
"""
from __future__ import annotations
import json
from datetime import date
from backend.v20_tech_swing_research import Bar, UNIVERSE, backtest


def evaluate():
    import yfinance as yf
    results = []
    for symbol in sorted(UNIVERSE - {"GOOG"}):
        frame = yf.download(symbol, start="2019-01-01", end="2026-11-18",
                            auto_adjust=True, progress=False, threads=False)
        if frame.empty or len(frame) < 700:
            raise RuntimeError(f"Missing sufficient historical bars: {symbol}")
        if hasattr(frame.columns, "nlevels") and frame.columns.nlevels > 1:
            frame.columns = frame.columns.get_level_values(0)
        bars = [Bar(day.date(), float(row["Open"]), float(row["High"]),
                    float(row["Low"]), float(row["Close"]), float(row["Volume"]))
                for day, row in frame.iterrows()]
        # Out-of-sample window: first 200 bars of 2023 as warm-up;
        # all trades and equity changes reported only from 2024 onward.
        sample = [b for b in bars if date(2023, 1, 1) <= b.day <= date(2026, 11, 17)]
        result = backtest(symbol, sample)
        baseline = (sample[-1].close / sample[200].open - 1) * 100
        result["buyHoldComparablePct"] = round(baseline, 2)
        result["dataStart"] = sample[0].day.isoformat()
        result["dataEnd"] = sample[-1].day.isoformat()
        results.append(result)
    print(json.dumps({"researchOnly": True, "liveOrders": 0,
                      "warning": "One-symbol simulations; not a combined portfolio, no parameter optimisation; includes synthetic friction, excludes taxes and dividends",
                      "results": results}, indent=2))


if __name__ == "__main__":
    evaluate()
