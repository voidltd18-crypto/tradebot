"""Research-only one-position portfolio selection with no broker connectivity."""
from __future__ import annotations
from backend.v20_tech_swing_research import UNIVERSE, validate, mean


def portfolio_backtest(history, capital=10000., allocation=0.25, friction_bps=15):
    if not history or not set(history).issubset(UNIVERSE):
        raise ValueError("Unknown or missing stock universe")
    if capital <= 0 or not (0 < allocation <= .25) or not (0 <= friction_bps <= 100):
        raise ValueError("Invalid risk limits")
    for bars in history.values():
        validate(bars)
    # Intersect dates: no filling missing bars with fabricated prices.
    dates = sorted(set.intersection(*(set(b.day for b in bars) for bars in history.values())))
    if len(dates) < 220:
        raise ValueError("Insufficient shared daily history")
    indexed = {sym: {b.day: b for b in bars} for sym, bars in history.items()}
    rows = {sym: [indexed[sym][day] for day in dates] for sym in history}
    closes = {sym: [b.close for b in bars] for sym, bars in rows.items()}
    cash, held, qty, entry_price, entry_i = float(capital), None, 0., 0., -1
    cooldown = {}
    trades, curve = [], []
    selections = []
    friction = friction_bps / 10000
    for i, day in enumerate(dates):
        if i >= 201:
            prev = i - 1
            exited = False
            if held is not None:
                bar = rows[held][i]
                c = closes[held]
                stop = entry_price * .92
                exit_price, reason = None, None
                if bar.low <= stop:
                    exit_price, reason = min(bar.open, stop), "STOP"
                elif c[prev] < mean(c[prev-199:prev+1]) and c[prev-1] < mean(c[prev-200:prev]):
                    exit_price, reason = bar.open, "LONG_TREND"
                elif i - entry_i >= 120:
                    exit_price, reason = bar.open, "MAX_HOLD"
                if exit_price is not None:
                    proceeds = qty * exit_price * (1 - friction)
                    cash += proceeds
                    trades.append({"symbol": held, "entryDay": dates[entry_i].isoformat(),
                                   "exitDay": day.isoformat(), "pnl": round(proceeds - qty * entry_price, 2),
                                   "reason": reason})
                    cooldown[held] = i + 10
                    held, qty, entry_price, entry_i = None, 0., 0., -1
                    exited = True
            if held is None and not exited:
                eligible = []
                for sym, c in closes.items():
                    if i <= cooldown.get(sym, -1):
                        continue
                    if c[prev] > mean(c[prev-49:prev+1]) > mean(c[prev-199:prev+1]) and c[prev] > c[prev-60]:
                        # 60-session relative momentum, fully known before entry.
                        eligible.append((c[prev] / c[prev-60] - 1, sym))
                if eligible:
                    _, held = max(eligible)
                    spend = cash * allocation
                    entry_price = rows[held][i].open * (1 + friction)
                    qty = spend / entry_price
                    cash -= spend
                    entry_i = i
                    selections.append({'day': day.isoformat(), 'symbol': held, 'momentum60': round(max(eligible)[0], 6)})
        curve.append(cash + (qty * rows[held][i].close if held else 0))
    peak, drawdown = curve[0], 0.
    for value in curve:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    return {"readOnly": True, "ordersSubmitted": 0, "onePosition": True,
            "totalReturnPct": round(100 * (curve[-1] / capital - 1), 2),
            "maxDrawdownPct": round(drawdown * 100, 2), "trades": trades,
            "closedTrades": len(trades), "openSymbolAtEnd": held,
            "entrySelections": selections,
            "start": dates[0].isoformat(), "end": dates[-1].isoformat(),
            "assumptions": {"maxAllocationPct": allocation*100, "maxHoldSessions": 120,
                            "frictionBpsPerSide": friction_bps,
                            "ranking": "60-session relative momentum, 50/200-day trend filter",
                            "sameBarReentry": False, "missingDates": "intersection only"}}
