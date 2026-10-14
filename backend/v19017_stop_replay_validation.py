"""V19.0.17 STOP replay-vs-realised reconciliation (read-only).

Reports the first sampled stop trigger and its difference from a verified
recorded exit. Samples are position marks, not executable bids.
"""
from datetime import datetime, timezone
from math import isfinite

def _time(v):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None

def stop_discrepancy(trade, points, replay_link, stop_pct=1.5):
    entry=float(trade.get("entry_price") or 0)
    fill=float(trade.get("exit_price") or 0)
    qty=float(trade.get("qty") or 0)
    outcome={"tradeId":trade.get("id"),"symbol":trade.get("symbol"),
             "replayLink":replay_link,"eligibleForCalibration":False,
             "warning":"Sampled position marks are not executable bids; no broker order causality is proved."}
    if not all(isfinite(x) and x>0 for x in (entry,fill,qty)):
        return {**outcome,"reason":"INVALID_TRADE_PRICE_OR_QTY"}
    exit_time=_time(trade.get("timestamp"))
    samples=[]
    for p in points:
        try:
            price=float(p.get("price") or 0)
            t=_time(p.get("point_time"))
            if t and isfinite(price) and price>0 and exit_time and t<=exit_time:
                samples.append((t,price))
        except (TypeError,ValueError,OverflowError):
            continue
    samples.sort()
    triggered=next(((t,p) for t,p in samples if (p/entry-1)*100<=-abs(stop_pct)),None)
    outcome["samplesBeforeExit"]=len(samples)
    outcome["actualExitPrice"]=round(fill,6)
    outcome["actualExitPct"]=round((fill/entry-1)*100,3)
    outcome["firstStopMarkPrice"]=round(triggered[1],6) if triggered else None
    outcome["firstStopMarkPct"]=round((triggered[1]/entry-1)*100,3) if triggered else None
    outcome["firstStopMarkTimeUtc"]=triggered[0].isoformat() if triggered else None
    outcome["markVsFillPp"]=round((triggered[1]-fill)/entry*100,3) if triggered else None
    outcome["markToRecordedExitSeconds"]=round((exit_time-triggered[0]).total_seconds(),1) if triggered and exit_time else None
    gaps=[(samples[i][0]-samples[i-1][0]).total_seconds() for i in range(1,len(samples))]
    outcome["maxSampleGapSeconds"]=round(max(gaps),1) if gaps else None
    issues=[]
    if replay_link!="direct":issues.append("UNVERIFIED_REPLAY_LINK")
    if len(samples)<2:issues.append("INSUFFICIENT_PRE_EXIT_MARKS")
    if not triggered:issues.append("NO_SAMPLED_STOP_TRIGGER")
    if outcome["maxSampleGapSeconds"] is not None and outcome["maxSampleGapSeconds"]>30:
        issues.append("SAMPLE_GAP_OVER_30S")
    outcome["issues"]=issues
    # A direct DB link is necessary but still not sufficient to prove an
    # executable fill or predict outcomes from an alternative live strategy.
    outcome["eligibleForCalibration"]=False
    outcome["reason"]="RESEARCH_ONLY_UNVERIFIED_EXECUTION"
    return outcome

def summary(rows):
    return {"tradesChecked":len(rows),
            "sampledStops":sum(r.get("firstStopMarkPrice") is not None for r in rows),
            "directReplayLinks":sum(r.get("replayLink")=="direct" for r in rows),
            "usableForAutomaticPromotion":0,
            "largestMarkFillDifferences":sorted(
                [r for r in rows if r.get("markVsFillPp") is not None],
                key=lambda x:abs(x["markVsFillPp"]),reverse=True)[:20],
            "liveTradingChanged":False,
            "note":"Read-only diagnostic. Stop marks may differ from actual executable bid/fills due to price sources, timing and uncertain replay linkage. No threshold recommendation is automatic."}
