"""V19.0.8: read-only realised trade economics and peak-leakage audit.

No trading authority, strategy mutation, broker requests, or auto-promotion.
Figures are recorded P&L, NOT necessarily net of costs. Do not use to
declare a strategy validated without independent fee/fill reconciliation.
"""
from math import isfinite

def profitability_audit(trades, replay_rows):
    valid = []
    rejected = 0
    for t in trades:
        try:
            pnl = float(t["pnl_gbp"])
            entry = float(t["entry_price"])
            exit_price = float(t["exit_price"])
            qty = float(t["qty"])
            if not all(map(isfinite, (pnl,entry,exit_price,qty))) or min(entry,exit_price,qty) <= 0:
                raise ValueError("invalid trade economics")
            valid.append((t,pnl))
        except (ValueError, TypeError, KeyError, OverflowError):
            rejected += 1
    pnls = [p for _,p in valid]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    gains = sum(winners)
    losses = -sum(losers)
    avg_win = gains/len(winners) if winners else 0.0
    avg_loss = losses/len(losers) if losers else 0.0
    payoff = avg_win/avg_loss if avg_loss > 0 else None
    leakage = []
    for row in replay_rows:
        try:
            peak = float(row["recordedPeakPct"])
            exit_pct = float(row["actualPnlPct"])
            if not isfinite(peak) or not isfinite(exit_pct):
                continue
            drop = max(0., peak-exit_pct)
            if drop >= 1.0:
                leakage.append({"tradeId":row.get("id"), "symbol":row.get("symbol"),
                                "sampledPeakPct":round(peak,4), "realisedExitPct":round(exit_pct,4),
                                "peakToExitPp":round(drop,4)})
        except (ValueError, TypeError, KeyError):
            continue
    leakage.sort(key=lambda x:x["peakToExitPp"],reverse=True)
    return {
        "version":"V19.0.8", "researchOnly":True, "liveTradingChanged":False,
        "closedTrades":len(trades), "validTrades":len(valid), "invalidTrades":rejected,
        "recordedPnlGbp":round(sum(pnls),2),
        "wins":len(winners), "losses":len(losers), "breakeven":len(pnls)-len(winners)-len(losers),
        "winRatePct":round(100*len(winners)/len(pnls),2) if pnls else None,
        "averageWinGbp":round(avg_win,4), "averageLossGbp":round(avg_loss,4),
        "payoffRatio":round(payoff,4) if payoff is not None else None,
        "breakEvenWinRatePct":round(100/(1+payoff),2) if payoff is not None else None,
        "profitFactor":round(gains/losses,4) if losses > 0 else None,
        "recordedExpectancyGbpPerTrade":round(sum(pnls)/len(pnls),4) if pnls else None,
        "worstRecordedLossGbp":round(min(losers),2) if losers else None,
        "sampledPeakLeakage":{"replayTrades":len(replay_rows),
            "tradesOver1pp":len(leakage), "largest":leakage[:20]},
        "validatedProfitability":False,
        "limitations":"Recorded closed_trades.pnl_gbp can omit commissions, FX, spread, slippage, and other costs; peak values are sampled, not guaranteed executable. No chronological out-of-sample validation or broker fill reconciliation performed.",
        "decision":"DO_NOT_AUTO_PROMOTE"
    }
