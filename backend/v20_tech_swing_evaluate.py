"""Offline research evaluation using public adjusted daily price history.

Research only; never imports Alpaca or sends orders.
Requires: pip install yfinance pandas
"""
from __future__ import annotations
import json
from datetime import date
from backend.v20_tech_swing_research import Bar, UNIVERSE, backtest
from backend.v20_tech_swing_trend_hold import trend_hold
from backend.v20_tech_swing_portfolio import portfolio_backtest
from backend.v20_tech_swing_passive import passive_basket
from backend.v20_tech_swing_release_gate import assess_release


def evaluate():
    import yfinance as yf
    results = []
    portfolio_history = {}
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
        # Historical research sample, NOT independent out-of-sample validation.
        # First 201 aligned sessions warm up indicators; trading may start in 2023.
        sample = [b for b in bars if date(2023, 1, 1) <= b.day <= date(2026, 11, 17)]
        portfolio_history[symbol] = sample
        result = backtest(symbol, sample)
        alternative = trend_hold(symbol, sample)
        result['trendHoldAlternative'] = {key: alternative[key] for key in ('totalReturnPct', 'maxDrawdownPct', 'closedTrades', 'openPositionAtEnd', 'assumptions')}
        result['trendHoldBeatsOriginal'] = alternative['totalReturnPct'] > result['totalReturnPct']
        baseline = (sample[-1].close / sample[200].open - 1) * 100
        result["buyHoldComparablePct"] = round(baseline, 2)
        result["buyHold25PctAllocationPct"] = round(baseline * 0.25, 2)
        closed = result["trades"]
        result["winningTrades"] = sum(1 for trade in closed if trade["pnl"] > 0)
        result["winRatePct"] = round(100 * result["winningTrades"] / len(closed), 2) if closed else None
        result["worstClosedTradeUsd"] = min((trade["pnl"] for trade in closed), default=None)
        result["outperformsMatchedAllocationBaseline"] = result["totalReturnPct"] > result["buyHold25PctAllocationPct"]
        result["dataStart"] = sample[0].day.isoformat()
        result["dataEnd"] = sample[-1].day.isoformat()
        results.append(result)
    combined = portfolio_backtest(portfolio_history)
    passive = passive_basket(portfolio_history)
    combined["matchedPassiveBasketReturnPct"] = passive["returnPct"]
    combined["matchedPassiveBasketDrawdownPct"] = passive["maxDrawdownPct"]
    combined["beatsMatchedPassiveBasket"] = combined["totalReturnPct"] > passive["returnPct"]
    combined["passiveBenchmarkMethod"] = "Date-aligned 25% equal-weight basket, 75% cash, 15bps each side"
    # Separate fresh-capital 2026 test with earlier bars for indicator warm-up.
    shared = sorted(set.intersection(*(set(b.day for b in bars) for bars in portfolio_history.values())))
    first2026 = next(i for i, day in enumerate(shared) if day.year == 2026)
    if first2026 >= 201:
        start = shared[first2026-201]
        subset = {sym: [b for b in bars if b.day >= start] for sym, bars in portfolio_history.items()}
        holdout = portfolio_backtest(subset)
        holdout_passive = passive_basket(subset)
        combined["freshCapital2026"] = {"returnPct": holdout["totalReturnPct"],
                                         "maxDrawdownPct": holdout["maxDrawdownPct"],
                                         "closedTrades": holdout["closedTrades"],
                                         "passiveReturnPct": holdout_passive["returnPct"],
                                         "passiveMaxDrawdownPct": holdout_passive["maxDrawdownPct"]}
    gate = assess_release(combined)
    print(json.dumps({"researchOnly": True, "liveOrders": 0, "releaseGate": gate, "portfolio": combined,
                      "warning": "Research simulations, not forward validation. Synthetic friction; excludes taxes and dividends; no live orders",
                      "results": results}, indent=2))


if __name__ == "__main__":
    evaluate()
