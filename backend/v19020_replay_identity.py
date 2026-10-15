"""V19.0.20 read-only replay identity guards.

A populated closed_trade_id is only a direct candidate. Identity still needs
symbol and exit-time consistency. This does not certify order causality.
"""
from datetime import datetime,timezone

def _parse(v):
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError,ValueError,OverflowError):
        return None

def direct_match(trade,session,max_seconds=3600):
    try:
        if int(session.get("closed_trade_id") or 0)!=int(trade.get("id") or 0):
            return False
    except (TypeError,ValueError):
        return False
    if not trade.get("id") or str(trade.get("symbol") or "").upper()!=str(session.get("symbol") or "").upper():
        return False
    ended=_parse(session.get("ended_at"))
    closed=_parse(trade.get("timestamp"))
    return bool(ended and closed and abs((ended-closed).total_seconds())<=max_seconds)

def unique_direct_sessions(trades,sessions):
    by_id={}
    trade_map={int(t["id"]):t for t in trades if t.get("id") is not None}
    for s in sessions:
        try: tid=int(s.get("closed_trade_id") or 0)
        except (TypeError,ValueError):continue
        if tid and tid in trade_map and direct_match(trade_map[tid],s):
            by_id.setdefault(tid,[]).append(s)
    return {tid:matches[0] for tid,matches in by_id.items() if len(matches)==1}
