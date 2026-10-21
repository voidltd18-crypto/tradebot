"""Read-only realised-trade expectancy report. Never decides or submits trades."""
from collections import defaultdict
from math import isfinite


def small_wins_audit(trades, small_win_gbp=5.0, min_trades=5):
    """Summarise actual realised GBP P&L by symbol.

    Input should be closed trades matched to broker fills. Zero-quantity
    artefacts and malformed amounts are excluded rather than counted as wins.
    Returns diagnostics, not a blocklist or buy/sell signal.
    """
    grouped = defaultdict(list)
    excluded = 0
    for row in trades:
        try:
            qty = float(row["qty"])
            pnl = float(row["pnlGbp"])
            symbol = str(row["symbol"]).upper().strip()
            if not symbol or not isfinite(qty) or qty <= 0 or not isfinite(pnl):
                raise ValueError("invalid trade")
        except (KeyError, TypeError, ValueError):
            excluded += 1
            continue
        grouped[symbol].append(pnl)
    rows = []
    for symbol, pnls in grouped.items():
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        small = [p for p in wins if p <= small_win_gbp]
        net = sum(pnls)
        rows.append({
            "symbol": symbol,
            "trades": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "smallWins": len(small),
            "smallWinSharePct": round(100 * len(small) / len(wins), 2) if wins else None,
            "netRealisedGbp": round(net, 2),
            "avgWinGbp": round(sum(wins) / len(wins), 2) if wins else None,
            "avgLossGbp": round(sum(losses) / len(losses), 2) if losses else None,
            "avgPnlPerTradeGbp": round(net / len(pnls), 2),
            "evidenceSufficient": len(pnls) >= min_trades,
        })
    rows.sort(key=lambda row: (row["avgPnlPerTradeGbp"], -row["trades"], row["symbol"]))
    return {
        "readOnly": True,
        "smallWinThresholdGbp": small_win_gbp,
        "minTradesForReview": min_trades,
        "excludedInvalidRows": excluded,
        "symbols": rows,
        "note": "Historical realised P&L is not a forecast; no stock is automatically blocked.",
    }
