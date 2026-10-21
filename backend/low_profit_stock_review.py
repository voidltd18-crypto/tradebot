"""Read-only evidence for stocks with weak historical realised profitability.

No trade placement or live eligibility changes. Review multiple completed,
positive-quantity trades before proposing a symbol for exclusion.
"""
from collections import defaultdict
from math import isfinite


def low_profit_stock_review(closed_trades, min_trades=5, max_winning_trade_gbp=5.0):
    if min_trades < 2 or max_winning_trade_gbp <= 0:
        raise ValueError("invalid low-profit review settings")
    groups = defaultdict(list)
    for trade in closed_trades:
        if not isinstance(trade, dict):
            continue
        symbol = str(trade.get("symbol") or "").upper().strip()
        try:
            quantity = float(trade.get("qty"))
            pnl = float(trade.get("pnlGbp"))
        except (ValueError, TypeError):
            continue
        if not symbol or not isfinite(quantity) or quantity <= 0 or not isfinite(pnl):
            continue
        groups[symbol].append(pnl)

    result = []
    for symbol, pnls in groups.items():
        wins = [p for p in pnls if p > 0]
        result.append({
            "symbol": symbol,
            "closedTrades": len(pnls),
            "winningTrades": len(wins),
            "maxWinGbp": round(max(wins, default=0), 2),
            "totalRealisedPnlGbp": round(sum(pnls), 2),
            "averageRealisedPnlGbp": round(sum(pnls) / len(pnls), 2),
            "reviewForExclusion": len(pnls) >= min_trades and max(wins, default=0) < max_winning_trade_gbp,
        })
    return sorted(result, key=lambda x: (not x["reviewForExclusion"], x["totalRealisedPnlGbp"], x["symbol"]))
