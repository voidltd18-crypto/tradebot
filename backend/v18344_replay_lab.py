"""V18.3.44 Replay Lab — read-only counterfactual exit simulator.

Uses saved stock Trade Replay price paths. It never submits orders and does not
change live entry/exit rules.
"""
from datetime import datetime, UTC, timedelta
from typing import Any, Dict, List
from fastapi import Request


def install_v18344_replay_lab(app, m) -> None:
    def _dt(v):
        try: return m._v6_parse_utc(v)
        except Exception: return None

    def _columns(conn, table):
        try: return [str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        except Exception: return []

    def _point_time_col(conn):
        cols = set(_columns(conn, "trade_replay_points"))
        for c in ("timestamp", "time", "recorded_at", "created_at", "observed_at", "sampled_at", "captured_at", "ts"):
            if c in cols: return c
        return None

    def _simulate(points, entry, qty, actual_exit, stop_pct, arm_pct, giveback_pct, stale_minutes, stale_max_peak_pct):
        if not points or entry <= 0 or qty <= 0:
            return None
        peak = entry
        start = _dt(points[0].get("point_time"))
        exit_price = actual_exit
        exit_reason = "ACTUAL END"
        exit_time = _dt(points[-1].get("point_time"))
        for p in points:
            price = float(p.get("price") or 0)
            if price <= 0: continue
            now = _dt(p.get("point_time"))
            peak = max(peak, price)
            pnl_pct = ((price / entry) - 1.0) * 100.0
            peak_pct = ((peak / entry) - 1.0) * 100.0
            if stop_pct > 0 and pnl_pct <= -abs(stop_pct):
                exit_price, exit_reason, exit_time = price, "STOP", now
                break
            if arm_pct > 0 and giveback_pct > 0 and peak_pct >= arm_pct and (peak_pct - pnl_pct) >= giveback_pct:
                exit_price, exit_reason, exit_time = price, "PEAK LOCK", now
                break
            if stale_minutes > 0 and start and now:
                held = (now-start).total_seconds()/60.0
                if held >= stale_minutes and peak_pct < stale_max_peak_pct and price <= entry:
                    exit_price, exit_reason, exit_time = price, "STALE", now
                    break
        sim_pnl_usd = (exit_price-entry)*qty
        return {"exitPrice":exit_price,"pnlUsd":sim_pnl_usd,"exitReason":exit_reason,
                "exitTime":exit_time.isoformat() if exit_time else None,
                "peakPct":((peak/entry)-1.0)*100.0}

    @app.get("/v18/replay-lab")
    def api_v18344_replay_lab(request: Request, days: int = 31, limit: int = 5000):
        m.verify_api_key(request)
        if not m.SQLITE_ENABLED:
            return {"ok":False,"message":"SQLite disabled"}
        days=max(1,min(int(days or 31),3660)); limit=max(50,min(int(limit or 5000),20000))
        cutoff=(datetime.now(UTC)-timedelta(days=days)).isoformat()
        conn=m.db_connect()
        try:
            time_col=_point_time_col(conn)
            point_cols=set(_columns(conn, "trade_replay_points"))
            order_col = time_col or ("id" if "id" in point_cols else "rowid")
            trades=[dict(r) for r in conn.execute(
                """SELECT * FROM closed_trades WHERE timestamp>=? AND COALESCE(qty,0)>?
                   AND ABS(COALESCE(qty,0)*COALESCE(exit_price,0))>=?
                   AND symbol NOT LIKE '%/%' ORDER BY timestamp DESC LIMIT ?""",
                (cutoff,m.PHANTOM_CLOSED_TRADE_QTY_EPSILON,m.PHANTOM_CLOSED_TRADE_MIN_NOTIONAL_USD,limit)).fetchall()]
            sessions=[dict(r) for r in conn.execute("SELECT * FROM trade_replay_sessions WHERE started_at>=? ORDER BY started_at DESC",(cutoff,)).fetchall()]
            direct={int(s["closed_trade_id"]):s for s in sessions if s.get("closed_trade_id") is not None}
            bysym={}
            for s in sessions: bysym.setdefault(str(s.get("symbol") or "").upper(),[]).append(s)
            def match(t):
                tid=int(t.get("id") or 0)
                if tid in direct: return direct[tid],"direct"
                sym=str(t.get("symbol") or "").upper(); td=_dt(t.get("timestamp")); entry=float(t.get("entry_price") or 0)
                best=None; score=1e99
                if not td:return None,None
                for s in bysym.get(sym,[]):
                    sd=_dt(s.get("ended_at") or s.get("started_at"))
                    if not sd:continue
                    delta=abs((td-sd).total_seconds())
                    se=float(s.get("entry_price") or 0)
                    diff=abs(se-entry)/entry if se>0 and entry>0 else 0
                    if delta<=1800 and diff<=0.03 and delta+diff*600<score:
                        best=s; score=delta+diff*600
                return (best,"reconciled") if best else (None,None)

            # Baseline mirrors the current protective stack concepts, while the
            # candidates deliberately vary one dimension at a time.
            configs=[
              {"key":"current_proxy","name":"Current-rule proxy","stop":1.50,"arm":1.25,"giveback":0.55,"stale":60,"stalePeak":0.75},
              {"key":"loss_125","name":"Tighter loss cap 1.25%","stop":1.25,"arm":1.25,"giveback":0.55,"stale":60,"stalePeak":0.75},
              {"key":"lock_100","name":"Earlier peak lock 1.00%","stop":1.50,"arm":1.00,"giveback":0.55,"stale":60,"stalePeak":0.75},
              {"key":"giveback_040","name":"Tighter giveback 0.40pp","stop":1.50,"arm":1.25,"giveback":0.40,"stale":60,"stalePeak":0.75},
              {"key":"stale_45","name":"Earlier stale exit 45m","stop":1.50,"arm":1.25,"giveback":0.55,"stale":45,"stalePeak":0.75},
            ]
            usable=[]; skipped=0
            for t in trades:
                sess,link=match(t)
                if not sess: skipped+=1; continue
                if time_col:
                    sql = 'SELECT price, "' + time_col + '" AS point_time FROM trade_replay_points WHERE session_id=? AND price>0 ORDER BY "' + order_col + '" ASC'
                    pts=[dict(r) for r in conn.execute(sql,(int(sess["id"]),)).fetchall()]
                else:
                    sql = "SELECT price FROM trade_replay_points WHERE session_id=? AND price>0 ORDER BY " + order_col + " ASC"
                    raw=[dict(r) for r in conn.execute(sql,(int(sess["id"]),)).fetchall()]
                    start=_dt(sess.get("started_at"))
                    pts=[{**p,"point_time":(start+timedelta(seconds=i*10)).isoformat() if start else None} for i,p in enumerate(raw)]
                if len(pts)<2: skipped+=1; continue
                entry=float(t.get("entry_price") or 0); qty=float(t.get("qty") or 0); actual_exit=float(t.get("exit_price") or 0)
                if entry<=0 or qty<=0 or actual_exit<=0: skipped+=1; continue
                fx=float(t.get("fx_rate") or 0)
                actual_gbp=float(t.get("pnl_gbp") or 0)
                if fx<=0:
                    usd=float(t.get("pnl") or 0); fx=(actual_gbp/usd) if usd else 0.75
                sims={}
                for cfg in configs:
                    s=_simulate(pts,entry,qty,actual_exit,cfg["stop"],cfg["arm"],cfg["giveback"],cfg["stale"],cfg["stalePeak"])
                    if s:
                        s["pnlGbp"]=s["pnlUsd"]*fx; s["deltaGbp"]=s["pnlGbp"]-actual_gbp
                        sims[cfg["key"]]=s
                usable.append({"id":int(t.get("id") or 0),"symbol":str(t.get("symbol") or ""),"timestamp":t.get("timestamp"),
                               "actualPnlGbp":actual_gbp,"actualPnlPct":float(t.get("pnl_pct") or 0),"replayLink":link,"simulations":sims})
            results=[]
            for cfg in configs:
                sims=[(r,r["simulations"].get(cfg["key"])) for r in usable if r["simulations"].get(cfg["key"])]
                pnls=[s["pnlGbp"] for _,s in sims]; actuals=[r["actualPnlGbp"] for r,_ in sims]
                wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<0]
                results.append({"key":cfg["key"],"name":cfg["name"],"trades":len(pnls),
                    "simPnlGbp":sum(pnls),"actualPnlGbp":sum(actuals),"deltaGbp":sum(pnls)-sum(actuals),
                    "winRatePct":len(wins)/len(pnls)*100 if pnls else 0,
                    "avgWinGbp":sum(wins)/len(wins) if wins else 0,"avgLossGbp":sum(losses)/len(losses) if losses else 0,
                    "payoffRatio":((sum(wins)/len(wins))/abs(sum(losses)/len(losses)) if wins and losses else 0),
                    "tailLossesOver10Gbp":sum(1 for x in losses if x<=-10),
                    "worstLossGbp":min(losses,default=0)})
            # V18.3.45 forensic view: expose every replayable trade and group
            # proxy divergence by the rule that fired.
            detail=[]
            reason_summary={}
            for r in usable:
                s=r["simulations"].get("current_proxy")
                if not s: continue
                row={**r,"proxyPnlGbp":s["pnlGbp"],"proxyDeltaGbp":s["deltaGbp"],
                     "proxyExitReason":s["exitReason"],"proxyExitPrice":s["exitPrice"],
                     "proxyExitTime":s["exitTime"],"recordedPeakPct":s["peakPct"]}
                detail.append(row)
                rs=reason_summary.setdefault(s["exitReason"],{"reason":s["exitReason"],"trades":0,"actualPnlGbp":0.0,"proxyPnlGbp":0.0,"deltaGbp":0.0})
                rs["trades"]+=1; rs["actualPnlGbp"]+=r["actualPnlGbp"]; rs["proxyPnlGbp"]+=s["pnlGbp"]; rs["deltaGbp"]+=s["deltaGbp"]
            detail=sorted(detail,key=lambda x:abs(x["proxyDeltaGbp"]),reverse=True)
            reasons=sorted(reason_summary.values(),key=lambda x:abs(x["deltaGbp"]),reverse=True)
            return {"ok":True,"version":"V18.3.45","days":days,"tradesScanned":len(trades),"replayTrades":len(usable),
                    "skippedNoReplay":skipped,"results":results,"largestChanges":detail[:20],
                    "tradeForensics":detail,"proxyReasonSummary":reasons,
                    "warning":"Counterfactual replay is diagnostic, not a guarantee. It uses recorded sampled prices, so exits can only trigger on saved replay points.",
                    "liveTradingChanged":False,"pointTimingMode":"recorded" if time_col else "synthesized-10s"}
        finally: conn.close()
