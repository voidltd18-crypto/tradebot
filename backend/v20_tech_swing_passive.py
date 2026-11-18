"""Research-only, date-aligned passive basket benchmark."""
from __future__ import annotations


def passive_basket(history, allocation=.25, friction_bps=15):
    if not history or not (0 < allocation <= 1) or not (0 <= friction_bps <= 100):
        raise ValueError("Invalid passive benchmark inputs")
    indexed = {sym: {b.day: b for b in bars} for sym, bars in history.items()}
    days = sorted(set.intersection(*(set(b) for b in indexed.values())))
    if len(days) < 220:
        raise ValueError("Insufficient aligned daily bars")
    first = 201
    fee = friction_bps / 10000
    symbols = sorted(indexed)
    cost = allocation / len(symbols)
    quantities = {sym: cost / (indexed[sym][days[first]].open * (1+fee)) for sym in symbols}
    curve = [1.] * first
    for day in days[first:]:
        equity = (1-allocation) + sum(quantities[sym] * indexed[sym][day].close for sym in symbols)
        curve.append(equity)
    peak, worst = curve[0], 0.
    for value in curve:
        peak = max(peak, value)
        worst = min(worst, value / peak - 1)
    liquidation = (1-allocation) + sum(quantities[sym] * indexed[sym][days[-1]].close * (1-fee) for sym in symbols)
    return {"returnPct": round(100*(liquidation-1), 2),
            "maxDrawdownPct": round(100*worst, 2),
            "readOnly": True, "ordersSubmitted": 0,
            "allocationPct": 100*allocation, "symbols": symbols,
            "firstTradeDay": days[first].isoformat(), "lastDay": days[-1].isoformat()}
