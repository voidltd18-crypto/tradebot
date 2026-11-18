"""Research-only mark-to-market evaluation of archived candidate signals.

A dated snapshot must predate the observed next session. This is NOT a trading
execution simulator, and it never authorizes or counts live-forward validation.
"""
from __future__ import annotations
from datetime import date, datetime
from backend.v20_tech_swing_forward_ledger import summarize_snapshots


def evaluate_observations(snapshot_paths, history):
    ledger = summarize_snapshots(snapshot_paths)
    if not history:
        raise ValueError("Missing market history")
    by_symbol = {}
    for symbol, bars in history.items():
        days = [b.day for b in bars]
        if days != sorted(set(days)):
            raise ValueError("History must be chronological with unique dates")
        by_symbol[symbol] = {b.day: b for b in bars}
    outcomes = []
    for record in ledger["candidateHistory"]:
        signal_day = date.fromisoformat(record["day"])
        symbol = record["topCandidate"]
        if not symbol:
            outcomes.append({"signalDay": record["day"], "symbol": None, "status": "NO_CANDIDATE"})
            continue
        bars = by_symbol.get(symbol)
        if not bars or signal_day not in bars:
            outcomes.append({"signalDay": record["day"], "symbol": symbol, "status": "MISSING_SIGNAL_BAR"})
            continue
        future = sorted(d for d in bars if d > signal_day)
        if len(future) < 2:
            outcomes.append({"signalDay": record["day"], "symbol": symbol, "status": "AWAITING_FUTURE_BARS"})
            continue
        entry_day, exit_day = future[:2]
        # Next-session open -> following-session open is a comparable, fixed
        # observation horizon. No assumed fills, stops, or live positions.
        entry = bars[entry_day].open
        exit_price = bars[exit_day].open
        raw = (exit_price / entry - 1) * 100
        outcomes.append({"signalDay": record["day"], "symbol": symbol,
                         "status": "OBSERVED", "entryDay": entry_day.isoformat(),
                         "exitDay": exit_day.isoformat(),
                         "nextSessionOpenToOpenPct": round(raw, 4)})
    observed = [x for x in outcomes if x["status"] == "OBSERVED"]
    return {"researchOnly": True, "ordersSubmitted": 0, "buyEnabled": False,
            "uniqueDatedSnapshots": ledger["uniqueDatedSnapshots"],
            "observedSignals": len(observed),
            "meanNextSessionOpenToOpenPct": round(sum(x["nextSessionOpenToOpenPct"] for x in observed)/len(observed), 4) if observed else None,
            "observations": outcomes,
            "forwardSessionsValidated": 0,
            "warning": "Observational open-to-open returns, no fill simulation, fees, position accounting, passive benchmark, or verified forward sessions."}
