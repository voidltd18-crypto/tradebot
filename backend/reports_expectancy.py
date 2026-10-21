"""Read-only closed-trade expectancy diagnostics, not a trading signal."""
import math


def recent_trade_expectancy(trades: list[dict]) -> dict:
    """Summarise strictly positive-quantity, finite realised GBP P&L records."""
    values = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        try:
            qty = float(trade.get("qty"))
            pnl = float(trade.get("pnlGbp"))
        except (TypeError, ValueError, OverflowError):
            continue
        if qty > 0 and math.isfinite(qty) and math.isfinite(pnl):
            values.append(pnl)
    wins = [x for x in values if x > 0]
    losses = [-x for x in values if x < 0]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    # Theoretical break-even win rate for these realised average amounts.
    denominator = avg_win + avg_loss
    return {
        "sampleTrades": len(values),
        "winners": len(wins),
        "losers": len(losses),
        "breakEven": len(values) - len(wins) - len(losses),
        "winRatePct": round(100 * len(wins) / len(values), 2) if values else None,
        "averageWinnerGbp": round(avg_win, 2) if wins else None,
        "averageLoserGbp": round(avg_loss, 2) if losses else None,
        "netRealisedGbp": round(sum(values), 2),
        "breakEvenWinRatePct": round(100 * avg_loss / denominator, 2) if wins and losses else None,
        "profitFactor": round(sum(wins) / sum(losses), 3) if losses else None,
        "readOnly": True,
        "sample": "latest closed-trade records; not lifetime",
    }
