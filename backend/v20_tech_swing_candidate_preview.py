"""Offline daily candidate preview. Never connects to broker or submits orders."""
from __future__ import annotations
from backend.v20_tech_swing_research import UNIVERSE, validate, mean


def candidate_preview(history, *, as_of=None):
    if not history or not set(history).issubset(UNIVERSE):
        raise ValueError("Unknown or empty universe")
    scores = []
    for symbol, bars in sorted(history.items()):
        validate(bars)
        eligible_bars = [b for b in bars if as_of is None or b.day <= as_of]
        if len(eligible_bars) < 201:
            scores.append({"symbol": symbol, "status": "INSUFFICIENT_DATA", "eligible": False})
            continue
        closes = [b.close for b in eligible_bars]
        last = closes[-1]
        ma50, ma200 = mean(closes[-50:]), mean(closes[-200:])
        momentum = 100 * (last / closes[-61] - 1)
        eligible = last > ma50 > ma200 and momentum > 0
        scores.append({"symbol": symbol, "status": "CANDIDATE" if eligible else "WAIT",
                       "eligible": eligible, "momentum60Pct": round(momentum, 2),
                       "asOf": eligible_bars[-1].day.isoformat()})
    candidates = [x for x in scores if x["eligible"]]
    candidates.sort(key=lambda x: (-x["momentum60Pct"], x["symbol"]))
    return {"readOnly": True, "ordersSubmitted": 0, "buyEnabled": False,
            "asOf": as_of.isoformat() if as_of else None,
            "topCandidate": candidates[0]["symbol"] if candidates else None,
            "rankedCandidates": candidates, "allSymbols": scores,
            "note": "Signals from completed daily bars only; not a live buy instruction."}
