"""Alternative research-only trend hold model, no broker access or orders.

Signals use yesterday's close; execution is at today's open. One position
per symbol; results are not a combined multi-symbol selection strategy.
"""
from __future__ import annotations
from backend.v20_tech_swing_research import validate, UNIVERSE, mean


def trend_hold(symbol, bars, *, capital=10000., allocation=0.25, friction_bps=15):
    if symbol not in UNIVERSE:
        raise ValueError("Symbol outside approved universe")
    validate(bars)
    if capital <= 0 or not (0 < allocation <= 0.25) or not (0 <= friction_bps <= 100):
        raise ValueError("Invalid risk parameters")
    closes = [b.close for b in bars]
    friction = friction_bps / 10000
    cash, qty, entry_i, entry_price = float(capital), 0., -1, 0.
    trades, curve = [], []
    cooldown_until = -1
    for i, bar in enumerate(bars):
        if i >= 201:
            prev = i - 1
            sma50 = mean(closes[prev-49:prev+1])
            sma200 = mean(closes[prev-199:prev+1])
            healthy = closes[prev] > sma50 > sma200
            if qty:
                # Exit on sustained long-term trend failure or 120 trading sessions;
                # an 8% catastrophic stop can gap beyond the stop price.
                stop = entry_price * 0.92
                if bar.low <= stop:
                    exit_px, reason = min(bar.open, stop), "CATASTROPHIC_STOP"
                elif closes[prev] < sma200 and closes[prev-1] < mean(closes[prev-200:prev]):
                    exit_px, reason = bar.open, "LONG_TREND_FAILURE"
                elif i - entry_i >= 120:
                    exit_px, reason = bar.open, "MAX_HOLD"
                else:
                    exit_px, reason = None, None
                if exit_px is not None:
                    proceeds = qty * exit_px * (1 - friction)
                    cash += proceeds
                    trades.append({"entryDay": bars[entry_i].day.isoformat(),
                                   "exitDay": bar.day.isoformat(), "pnl": round(proceeds - qty * entry_price, 2),
                                   "reason": reason})
                    qty, entry_i, entry_price = 0., -1, 0.
                    cooldown_until = i + 10
            # Never exit and reenter on same bar; wait at least 10 sessions.
            if not qty and i > cooldown_until and healthy and closes[prev] > closes[prev-20]:
                spend = cash * allocation
                entry_price = bar.open * (1 + friction)
                qty = spend / entry_price
                cash -= spend
                entry_i = i
        curve.append(cash + qty * bar.close)
    peak, drawdown = curve[0], 0.
    for equity in curve:
        peak = max(peak, equity)
        drawdown = min(drawdown, equity / peak - 1)
    return {"symbol": symbol, "readOnly": True, "ordersSubmitted": 0,
            "totalReturnPct": round(100 * (curve[-1] / capital - 1), 2),
            "maxDrawdownPct": round(drawdown * 100, 2),
            "closedTrades": len(trades), "trades": trades, "openPositionAtEnd": bool(qty),
            "assumptions": {"maxAllocationPct": allocation * 100, "maxHoldSessions": 120,
                            "cooldownSessions": 10, "catastrophicStopPct": 8,
                            "frictionBpsPerSide": friction_bps,
                            "intradayStopAssumption": "stop fills at stop or worse gap open"}}
