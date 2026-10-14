"""V19.0.15 replay evidence-quality audit (read-only).

Flags mismatches between replay paths and realised executions. Does not change
existing counterfactual P&L and does not submit orders.
"""
from datetime import datetime, timezone
from math import isfinite

def _utc(value):
    if not value: return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError): return None

def evidence_quality(trade,session,points,link,fx_source):
    flags=[]
    end=_utc(trade.get("timestamp"))
    observed=[_utc(p.get("point_time")) for p in points]
    valid=[t for t in observed if t]
    if link!="direct":flags.append("REPLAY_LINK_NOT_DIRECT")
    if len(points)<2:flags.append("TOO_FEW_POINTS")
    if len(valid)!=len(points):flags.append("INVALID_OR_SYNTHETIC_POINT_TIME")
    if end and valid:
        lag=(end-max(valid)).total_seconds()
        if lag>60: flags.append("LAST_SAMPLE_OVER_60S_BEFORE_EXIT")
        if lag< -30: flags.append("REPLAY_CONTINUES_OVER_30S_AFTER_EXIT")
    else:
        lag=None
        flags.append("EXIT_OR_SAMPLE_TIMESTAMP_UNAVAILABLE")
    prices=[]
    for p in points:
        try:
            value=float(p.get("price"))
            if isfinite(value) and value>0:prices.append(value)
        except (ValueError,TypeError):pass
    if not prices:flags.append("NO_VALID_PRICES")
    if fx_source!="recorded":flags.append("FX_RATE_NOT_RECORDED")
    if not trade.get("reason"):flags.append("MISSING_EXIT_REASON")
    return {"tradeId":trade.get("id"),"symbol":trade.get("symbol"),
            "link":link,"samples":len(points),"lastSampleToExitSeconds":round(lag,1) if lag is not None else None,
            "fxSource":fx_source,"flags":flags,"quality":"LIMITED" if flags else "ELIGIBLE_FOR_FURTHER_VALIDATION"}

def quality_summary(rows):
    counts={}
    for row in rows:
        for flag in row["flags"]:
            counts[flag]=counts.get(flag,0)+1
    return {"tradesChecked":len(rows),
            "cleanEvidenceCount":sum(not r["flags"] for r in rows),
            "flagCounts":counts,
            "topFlagged":sorted((r for r in rows if r["flags"]),key=lambda r:len(r["flags"]),reverse=True)[:30],
            "strategyValidated":False,"liveTradingChanged":False,
            "note":"Even clean sampled paths are NOT executable bids and cannot establish fill-level counterfactual P&L. Existing simulations are unchanged."}
