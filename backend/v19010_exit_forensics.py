"""V19.0.10 read-only stock exit execution forensics.

Recorded peaks are sampled broker position prices, NOT actionable bid prices.
No orders or changes to broker, risk or exit paths.
"""
from datetime import datetime, timezone, timedelta
from fastapi import Request

def summarize_exit_path(points, exit_price, entry_price):
    """Return observability facts; avoid claiming missed executable profit."""
    valid = []
    for p in points:
        try:
            price = float(p.get("price") or 0)
            ts = p.get("observed_at")
            dt = datetime.fromisoformat(str(ts).replace("Z","+00:00"))
            if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
            if price > 0 and price < float("inf") and dt:
                valid.append((dt,price))
        except (ValueError,TypeError,OverflowError):
            continue
    valid.sort()
    if not valid or entry_price <= 0 or exit_price <= 0:
        return {"coverage":"INSUFFICIENT","samples":len(valid)}
    gaps = [(valid[i][0]-valid[i-1][0]).total_seconds() for i in range(1,len(valid))]
    peak_time,peak_price=max(valid,key=lambda p:p[1])
    final_time,final_price=valid[-1]
    lag=(final_time-peak_time).total_seconds()
    peak_pct=(peak_price/entry_price-1)*100
    exit_pct=(exit_price/entry_price-1)*100
    return {"coverage":"SAMPLED_ONLY","samples":len(valid),
        "largestSampleGapSec":round(max(gaps),1) if gaps else None,
        "lastSampleTimeUtc":final_time.isoformat(),
        "lastObservedPrice":round(final_price,6),
        "peakSampleTimeUtc":peak_time.isoformat(),
        "peakSamplePrice":round(peak_price,6),
        "peakPct":round(peak_pct,3),"exitPct":round(exit_pct,3),
        "sampledGivebackPp":round(max(0,peak_pct-exit_pct),3),
        "secondsFromPeakToLastSample":round(lag,1),
        "priceMovementAfterLastSamplePct":round((exit_price/final_price-1)*100,3),
        "notAnExecutableQuote":True}

def install_v19010_exit_forensics(app,m):
    @app.get("/v19/stock-exit-forensics")
    def get_forensics(request: Request, days:int=31, limit:int=100):
        m.verify_api_key(request)
        if not m.SQLITE_ENABLED:
            return {"ok":False,"message":"SQLite disabled"}
        days=max(1,min(int(days),366));limit=max(1,min(int(limit),500))
        since=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        conn=m.db_connect()
        try:
            trades=[dict(r) for r in conn.execute(
                """SELECT id,symbol,timestamp,entry_price,exit_price,pnl_gbp,pnl_pct
                   FROM closed_trades WHERE timestamp>=? AND symbol NOT LIKE '%/%'
                   ORDER BY timestamp DESC LIMIT ?""",(since,limit)).fetchall()]
            try:
                audit_cols={r["name"] for r in conn.execute("PRAGMA table_info(stock_exit_decision_audit)")}
            except Exception:
                audit_cols=set()
            rows=[]
            for trade in trades:
                session=conn.execute(
                    """SELECT id FROM trade_replay_sessions
                       WHERE closed_trade_id=? ORDER BY id DESC LIMIT 1""",
                    (trade["id"],)).fetchone()
                if session is None:
                    rows.append({"tradeId":trade["id"],"symbol":trade["symbol"],
                                 "coverage":"NO_DIRECT_REPLAY_SESSION"})
                    continue
                pc={r["name"] for r in conn.execute("PRAGMA table_info(trade_replay_points)")}
                time_col=next((c for c in ("observed_at","timestamp","recorded_at","created_at","sampled_at","captured_at","time","ts") if c in pc),None)
                if not time_col:
                    rows.append({"tradeId":trade["id"],"symbol":trade["symbol"],"coverage":"MISSING_POINT_TIMESTAMPS"})
                    continue
                pts=[dict(p) for p in conn.execute(
                    f'SELECT price,"{time_col}" AS observed_at FROM trade_replay_points WHERE session_id=? ORDER BY "{time_col}"',
                    (session["id"],)).fetchall()]
                evidence=summarize_exit_path(pts,float(trade["exit_price"] or 0),float(trade["entry_price"] or 0))
                audit=[]
                if {"session_id","reason","observed_at"}.issubset(audit_cols):
                    audit=[dict(a) for a in conn.execute(
                        "SELECT observed_at,reason,source FROM stock_exit_decision_audit WHERE session_id=? ORDER BY observed_at DESC LIMIT 3",
                        (session["id"],)).fetchall()]
                rows.append({"tradeId":trade["id"],"symbol":trade["symbol"],
                             "exitAt":trade["timestamp"],"recordedPnlGbp":trade["pnl_gbp"],
                             "exitDecisions":audit,"path":evidence})
            return {"ok":True,"version":"V19.0.10","liveTradingChanged":False,
                    "directMatched":sum(1 for r in rows if "path" in r),
                    "tradesScanned":len(trades),"rows":rows,
                    "warning":"Position snapshots are not executable bids. No reliable order-submit/fill latency can be computed from these tables. Direct replay associations only; unmatched sessions are explicitly excluded."}
        finally:
            conn.close()
