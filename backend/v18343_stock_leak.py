"""V18.3.43 Stock Leak Analyzer override.

Keeps the large legacy monolith untouched while replacing only the diagnostic
/v18/stock-leak-analysis route at application assembly time.
"""
from datetime import datetime, UTC, timedelta
from typing import Any, Dict, List
from zoneinfo import ZoneInfo
from fastapi import Request


def install_v18343(app, m) -> None:
    # Remove the V18.3.42 diagnostic route registered by the legacy monolith.
    app.router.routes[:] = [
        route for route in app.router.routes
        if not (getattr(route, "path", None) == "/v18/stock-leak-analysis" and "GET" in (getattr(route, "methods", set()) or set()))
    ]

    def analyse(days: int = 31, limit: int = 5000) -> Dict[str, Any]:
        if not m.SQLITE_ENABLED:
            return {"ok": False, "message": "SQLite disabled"}
        try:
            m._trade_replay_ensure_tables()
        except Exception:
            pass
        days = max(1, min(int(days or 31), 3660))
        limit = max(50, min(int(limit or 5000), 20000))
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        current_rules_since = "2026-10-01T00:00:00+00:00"
        conn = m.db_connect()
        try:
            trades = [dict(r) for r in conn.execute(
                """SELECT * FROM closed_trades
                   WHERE timestamp>=? AND COALESCE(qty,0)>?
                     AND ABS(COALESCE(qty,0)*COALESCE(exit_price,0))>=?
                     AND symbol NOT LIKE '%/%'
                   ORDER BY timestamp DESC LIMIT ?""",
                (cutoff, m.PHANTOM_CLOSED_TRADE_QTY_EPSILON, m.PHANTOM_CLOSED_TRADE_MIN_NOTIONAL_USD, limit),
            ).fetchall()]

            try:
                replay_sessions = [dict(r) for r in conn.execute(
                    "SELECT * FROM trade_replay_sessions WHERE started_at>=? ORDER BY started_at DESC", (cutoff,)
                ).fetchall()]
            except Exception:
                replay_sessions = []

            direct = {int(r["closed_trade_id"]): r for r in replay_sessions if r.get("closed_trade_id") is not None}
            by_symbol: Dict[str, List[Dict[str, Any]]] = {}
            for sess in replay_sessions:
                by_symbol.setdefault(str(sess.get("symbol") or "").upper(), []).append(sess)

            def parse_dt(v):
                try:
                    return m._v6_parse_utc(v)
                except Exception:
                    return None

            def replay_for_trade(t):
                tid = int(t.get("id") or 0)
                if tid in direct:
                    return direct[tid], "direct"
                sym = str(t.get("symbol") or "").upper()
                exit_dt = parse_dt(t.get("timestamp"))
                entry = float(t.get("entry_price") or 0)
                if not sym or not exit_dt:
                    return None, None
                best = None
                best_score = 1e18
                for sess in by_symbol.get(sym, []):
                    st = parse_dt(sess.get("started_at"))
                    en = parse_dt(sess.get("ended_at"))
                    if not st:
                        continue
                    anchor = en or st
                    delta = abs((exit_dt - anchor).total_seconds())
                    if delta > 1800:
                        continue
                    sess_entry = float(sess.get("entry_price") or 0)
                    entry_diff = (abs(sess_entry-entry)/entry) if entry > 0 and sess_entry > 0 else 0.0
                    if entry_diff > 0.03:
                        continue
                    score = delta + entry_diff * 600.0
                    if score < best_score:
                        best, best_score = sess, score
                return (best, "reconciled") if best else (None, None)

            rows = []
            for t in trades:
                tid = int(t.get("id") or 0)
                entry = float(t.get("entry_price") or 0)
                pnl = float(t.get("pnl") or 0)
                pnl_gbp = float(t.get("pnl_gbp") or 0)
                pnl_pct = float(t.get("pnl_pct") or 0)
                sess, replay_link = replay_for_trade(t)
                hold_min = max_gain = max_dd = capture = None
                if sess:
                    st = parse_dt(sess.get("started_at"))
                    en = parse_dt(sess.get("ended_at") or t.get("timestamp"))
                    if st and en:
                        hold_min = max(0.0, (en-st).total_seconds()/60.0)
                    try:
                        pts = conn.execute(
                            "SELECT MIN(price) lo, MAX(price) hi FROM trade_replay_points WHERE session_id=? AND price>0",
                            (int(sess["id"]),),
                        ).fetchone()
                    except Exception:
                        pts = None
                    if pts and entry > 0:
                        hi = float(pts["hi"] or 0)
                        lo = float(pts["lo"] or 0)
                        if hi > 0:
                            max_gain = ((hi/entry)-1.0)*100.0
                        if lo > 0:
                            max_dd = ((lo/entry)-1.0)*100.0
                        if max_gain is not None and max_gain > 0 and pnl_pct > 0:
                            capture = max(0.0, min(200.0, (pnl_pct/max_gain)*100.0))
                dt = parse_dt(t.get("timestamp"))
                hour = int(dt.astimezone(ZoneInfo("Europe/London")).hour) if dt else None
                rows.append({
                    "id": tid, "symbol": str(t.get("symbol") or ""), "timestamp": t.get("timestamp"),
                    "reason": str(t.get("reason") or "UNKNOWN"), "source": str(t.get("source") or ""),
                    "pnlUsd": pnl, "pnlGbp": pnl_gbp, "pnlPct": pnl_pct, "holdMinutes": hold_min,
                    "maxGainPct": max_gain, "maxDrawdownPct": max_dd, "capturePct": capture,
                    "exitHourUk": hour, "replayLink": replay_link,
                    "currentRules": bool(dt and dt >= m._v6_parse_utc(current_rules_since)),
                })

            def avg(vals):
                vals = [float(v) for v in vals if v is not None]
                return sum(vals)/len(vals) if vals else None

            def summarize(rs):
                wins = [r for r in rs if r["pnlUsd"] > 0]
                losses = [r for r in rs if r["pnlUsd"] < 0]
                aw = avg([r["pnlGbp"] for r in wins]) or 0.0
                al = avg([r["pnlGbp"] for r in losses]) or 0.0
                return {
                    "trades": len(rs), "wins": len(wins), "losses": len(losses),
                    "winRatePct": (len(wins)/len(rs)*100.0 if rs else 0.0),
                    "netPnlGbp": sum(r["pnlGbp"] for r in rs), "avgWinGbp": aw, "avgLossGbp": al,
                    "payoffRatio": (aw/abs(al) if al else 0.0),
                    "avgWinnerHoldMin": avg([r["holdMinutes"] for r in wins]),
                    "avgLoserHoldMin": avg([r["holdMinutes"] for r in losses]),
                    "avgWinnerMaxGainPct": avg([r["maxGainPct"] for r in wins]),
                    "avgLoserMaxGainPct": avg([r["maxGainPct"] for r in losses]),
                    "avgWinnerCapturePct": avg([r["capturePct"] for r in wins]),
                    "replayCoverage": sum(1 for r in rs if r["holdMinutes"] is not None),
                    "tailLossesOver10Gbp": sum(1 for r in losses if r["pnlGbp"] <= -10.0),
                    "worstLossGbp": min([r["pnlGbp"] for r in losses], default=0.0),
                }

            summary = summarize(rows)
            current_rows = [r for r in rows if r["currentRules"]]
            historical_rows = [r for r in rows if not r["currentRules"]]

            def group(rs, key):
                buckets = {}
                for r in rs:
                    k = r.get(key)
                    if k is None:
                        continue
                    buckets.setdefault(str(k), []).append(r)
                out = []
                for k, xs in buckets.items():
                    out.append({
                        "name": k, "trades": len(xs),
                        "winRatePct": sum(1 for r in xs if r["pnlUsd"] > 0)/len(xs)*100.0,
                        "pnlGbp": sum(r["pnlGbp"] for r in xs),
                        "avgPnlGbp": sum(r["pnlGbp"] for r in xs)/len(xs),
                    })
                return out

            by_reason = sorted(group(rows, "reason"), key=lambda x: x["pnlGbp"])
            by_symbol_rows = sorted(group(rows, "symbol"), key=lambda x: x["pnlGbp"])
            by_hour = sorted(group(rows, "exitHourUk"), key=lambda x: int(x["name"]))
            losses = [r for r in rows if r["pnlUsd"] < 0]
            biggest_losses = sorted(losses, key=lambda r: r["pnlGbp"])[:10]
            gave_back = [r for r in rows if r["maxGainPct"] is not None and r["maxGainPct"] > 0.20 and r["pnlPct"] < r["maxGainPct"]-0.20]
            gave_back = sorted(gave_back, key=lambda r: (r["maxGainPct"]-r["pnlPct"]), reverse=True)[:10]
            return {
                "ok": True, "version": "V18.3.43", "days": days, "summary": summary,
                "currentRulesSince": current_rules_since, "currentRules": summarize(current_rows),
                "historicalBeforeCurrentRules": summarize(historical_rows),
                "byExitReason": by_reason[:20], "bySymbol": by_symbol_rows[:20], "byExitHourUk": by_hour,
                "biggestLosses": biggest_losses, "largestGivebacks": gave_back,
                "replayDirect": sum(1 for r in rows if r["replayLink"] == "direct"),
                "replayReconciled": sum(1 for r in rows if r["replayLink"] == "reconciled"),
                "note": "Stock-only, read-only evidence. Current-rule split starts 01/10/2026; replay is linked directly where possible and reconciled by symbol/time/entry for older sessions.",
            }
        finally:
            conn.close()

    @app.get("/v18/stock-leak-analysis")
    def api_v18343_stock_leak_analysis(request: Request, days: int = 31, limit: int = 5000):
        m.verify_api_key(request)
        return analyse(days, limit)
