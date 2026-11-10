"""Decision helper for repeat underperformers. Only blocks new buys."""
from collections import defaultdict
from math import isfinite


def weak_symbols_by_realised_trades(rows, *, min_trades=3, profit_threshold_gbp=5.0):
    """Return symbol diagnostics using distinct broker sell orders.

    rows: (symbol, sell_order_id, total_realised_pnl_gbp) aggregated per sell order.
    Incomplete/legacy rows without a verified sell ID are not counted.
    A symbol is weak only when >=min_trades distinct sell orders have ALL
    produced <= profit_threshold_gbp. Past performance is not a prediction.
    """
    if min_trades < 1 or not isfinite(profit_threshold_gbp):
        raise ValueError("invalid low-profit gate configuration")
    by_symbol = defaultdict(dict)
    for symbol, order_id, pnl in rows:
        symbol = str(symbol or "").upper().strip()
        order_id = str(order_id or "").strip()
        try:
            amount = float(pnl)
        except (TypeError, ValueError, OverflowError):
            continue
        if symbol and order_id and isfinite(amount):
            by_symbol[symbol][order_id] = amount
    return {
        symbol: {"trades": len(values), "bestTradeGbp": round(max(values.values()), 2)}
        for symbol, values in by_symbol.items()
        if len(values) >= min_trades and max(values.values()) <= profit_threshold_gbp
    }
