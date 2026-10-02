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
            usable=[]; skipped=0; replay_paths={}
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
                trade_id=int(t.get("id") or 0)
                replay_paths[trade_id]={"points":pts,"entry":entry,"actualExit":actual_exit}
                usable.append({"id":trade_id,"symbol":str(t.get("symbol") or ""),"timestamp":t.get("timestamp"),
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
            # V18.3.46 Exit Intelligence Lab: diagnose whether defensive proxy
            # triggers fired on genuine failures or on trades that later recovered.
            exit_intelligence=[]
            exit_summary={}
            for row in detail:
                reason=str(row.get("proxyExitReason") or "")
                if reason not in ("STOP","STALE"): continue
                actual=float(row.get("actualPnlGbp") or 0)
                proxy=float(row.get("proxyPnlGbp") or 0)
                delta=actual-proxy
                if actual > 0 and proxy < actual:
                    outcome="RECOVERED WINNER"
                elif actual >= 0 and proxy < 0:
                    outcome="RECOVERED / AVOIDED LOSS"
                elif actual < 0 and proxy > actual:
                    outcome="PROTECTION HELPED"
                elif actual < proxy:
                    outcome="PROXY WORSE"
                else:
                    outcome="SIMILAR"
                item={**row,"forensicOutcome":outcome,"recoveryValueGbp":delta,
                      "actualWinner":actual>0,"proxyWinner":proxy>0}
                exit_intelligence.append(item)
                key=f"{reason} · {outcome}"
                g=exit_summary.setdefault(key,{"trigger":reason,"outcome":outcome,"trades":0,
                    "actualPnlGbp":0.0,"proxyPnlGbp":0.0,"recoveryValueGbp":0.0})
                g["trades"]+=1; g["actualPnlGbp"]+=actual; g["proxyPnlGbp"]+=proxy; g["recoveryValueGbp"]+=delta
            exit_intelligence=sorted(exit_intelligence,key=lambda x:abs(x["recoveryValueGbp"]),reverse=True)
            exit_summary=sorted(exit_summary.values(),key=lambda x:abs(x["recoveryValueGbp"]),reverse=True)
            # V18.3.47 Recovery-Aware Exit Research: measure the price behaviour
            # around STOP/STALE triggers without changing any live rule.
            recovery_research=[]
            recovery_groups={}
            for row in exit_intelligence:
                path=replay_paths.get(int(row.get("id") or 0)) or {}
                pts=path.get("points") or []; entry=float(path.get("entry") or 0)
                trigger_time=_dt(row.get("proxyExitTime"))
                trigger_idx=None
                if trigger_time:
                    best_gap=1e99
                    for i,p in enumerate(pts):
                        pt=_dt(p.get("point_time"))
                        if pt:
                            gap=abs((pt-trigger_time).total_seconds())
                            if gap<best_gap: best_gap=gap; trigger_idx=i
                if trigger_idx is None:
                    target=float(row.get("proxyExitPrice") or 0)
                    trigger_idx=min(range(len(pts)),key=lambda i:abs(float(pts[i].get("price") or 0)-target)) if pts else 0
                prices=[float(p.get("price") or 0) for p in pts]
                tp=prices[trigger_idx] if prices and trigger_idx<len(prices) else 0
                def mom(back):
                    j=max(0,trigger_idx-back); old=prices[j] if prices else 0
                    return ((tp/old)-1)*100 if tp>0 and old>0 else 0
                before=prices[max(0,trigger_idx-6):trigger_idx+1]
                after=prices[trigger_idx+1:]
                pre_peak=max(before,default=tp)
                post_peak=max(after,default=tp)
                post_low=min(after,default=tp)
                reclaim_entry=bool(entry>0 and post_peak>=entry)
                post_best_pct=((post_peak/tp)-1)*100 if tp>0 else 0
                post_worst_pct=((post_low/tp)-1)*100 if tp>0 else 0
                drawdown_from_recent=((tp/pre_peak)-1)*100 if tp>0 and pre_peak>0 else 0
                actual=float(row.get("actualPnlGbp") or 0); proxy=float(row.get("proxyPnlGbp") or 0)
                research_label="RECOVERY" if actual>proxy and (actual>=0 or reclaim_entry) else "FAILURE / PROTECTION"
                rr={**row,"researchLabel":research_label,"momentum1Pct":mom(1),"momentum3Pct":mom(3),
                    "momentum6Pct":mom(6),"recentDrawdownPct":drawdown_from_recent,
                    "postTriggerBestPct":post_best_pct,"postTriggerWorstPct":post_worst_pct,
                    "reclaimedEntry":reclaim_entry,"samplesBefore":len(before),"samplesAfter":len(after)}
                recovery_research.append(rr)
                key=f"{row.get('proxyExitReason')} · {research_label}"
                g=recovery_groups.setdefault(key,{"trigger":row.get("proxyExitReason"),"label":research_label,"trades":0,
                    "avgMomentum3Pct":0.0,"avgRecentDrawdownPct":0.0,"avgPostTriggerBestPct":0.0,
                    "reclaimedEntryTrades":0,"actualPnlGbp":0.0,"proxyPnlGbp":0.0})
                g["trades"]+=1; g["avgMomentum3Pct"]+=rr["momentum3Pct"]; g["avgRecentDrawdownPct"]+=rr["recentDrawdownPct"]
                g["avgPostTriggerBestPct"]+=post_best_pct; g["reclaimedEntryTrades"]+=1 if reclaim_entry else 0
                g["actualPnlGbp"]+=actual; g["proxyPnlGbp"]+=proxy
            recovery_summary=[]
            for g in recovery_groups.values():
                n=max(1,g["trades"])
                g["avgMomentum3Pct"]/=n; g["avgRecentDrawdownPct"]/=n; g["avgPostTriggerBestPct"]/=n
                g["reclaimRatePct"]=g["reclaimedEntryTrades"]/n*100
                recovery_summary.append(g)
            recovery_research=sorted(recovery_research,key=lambda x:abs(float(x.get("recoveryValueGbp") or 0)),reverse=True)
            recovery_summary=sorted(recovery_summary,key=lambda x:(x["trigger"],x["label"]))

            return {"ok":True,"version":"V18.3.47","days":days,"tradesScanned":len(trades),"replayTrades":len(usable),
                    "skippedNoReplay":skipped,"results":results,"largestChanges":detail[:20],
                    "tradeForensics":detail,"proxyReasonSummary":reasons,
                    "exitIntelligence":exit_intelligence,"exitIntelligenceSummary":exit_summary,\n                    "recoveryAwareResearch":recovery_research,"recoveryAwareSummary":recovery_summary,
                    "warning":"Counterfactual replay is diagnostic, not a guarantee. It uses recorded sampled prices, so exits can only trigger on saved replay points.",
                    "liveTradingChanged":False,"pointTimingMode":"recorded" if time_col else "synthesized-10s"}
        finally: conn.close()
