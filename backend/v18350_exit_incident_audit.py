"""V18.3.50 Stock Exit Incident Audit.

Read-only diagnostics for recent closed stock losses. This module does not
submit orders or alter live entry/exit rules.
"""
from datetime import datetime, UTC
from fastapi import Request


def install_v18350_exit_incident_audit(app, m) -> None:
    @app.get("/v18/exit-incident-audit")
    def api_exit_incident_audit(request: Request):
        m.verify_api_key(request)
        if not m.SQLITE_ENABLED:
            return {"ok": False, "message": "SQLite disabled"}

        since = datetime(2026, 10, 2, tzinfo=UTC)
        conn = m.db_connect()
        try:
            trades = [dict(r) for r in conn.execute(
                """SELECT * FROM closed_trades
                   WHERE timestamp>=? AND COALESCE(qty,0)>?
                     AND ABS(COALESCE(qty,0)*COALESCE(exit_price,0))>=?
                     AND symbol NOT LIKE '%/%'
                     AND COALESCE(pnl_gbp,0)<0
                   ORDER BY timestamp DESC LIMIT 200""",
                (since.isoformat(), m.PHANTOM_CLOSED_TRADE_QTY_EPSILON,
                 m.PHANTOM_CLOSED_TRADE_MIN_NOTIONAL_USD),
            ).fetchall()]

            try:
                sessions = [dict(r) for r in conn.execute(
                    "SELECT * FROM trade_replay_sessions WHERE started_at>=? ORDER BY started_at DESC",
                    (since.isoformat(),),
                ).fetchall()]
            except Exception:
                sessions = []

            direct = {int(s["closed_trade_id"]): s for s in sessions if s.get("closed_trade_id") is not None}
            by_symbol = {}
            for s in sessions:
                by_symbol.setdefault(str(s.get("symbol") or "").upper(), []).append(s)

            def dt(v):
                try:
                    return m._v6_parse_utc(v)
                except Exception:
                    return None

            def match(t):
                tid = int(t.get("id") or 0)
                if tid in direct:
                    return direct[tid], "direct"
                sym = str(t.get("symbol") or "").upper()
                td = dt(t.get("timestamp"))
                entry = float(t.get("entry_price") or 0)
                best = None
                score = 1e99
                if not td:
                    return None, None
                for s in by_symbol.get(sym, []):
                    sd = dt(s.get("ended_at") or s.get("started_at"))
                    if not sd:
                        continue
                    delta = abs((td - sd).total_seconds())
                    se = float(s.get("entry_price") or 0)
                    diff = abs(se-entry)/entry if se > 0 and entry > 0 else 0
                    if delta <= 1800 and diff <= 0.03 and delta + diff*600 < score:
                        best, score = s, delta + diff*600
                return (best, "reconciled") if best else (None, None)

            rows = []
            for t in trades:
                sess, link = match(t)
                status = "NO REPLAY SESSION"
                points = 0
                low = high = None
                if sess:
                    try:
                        p = conn.execute(
                            "SELECT COUNT(*) c, MIN(price) lo, MAX(price) hi FROM trade_replay_points WHERE session_id=? AND price>0",
                            (int(sess["id"]),),
                        ).fetchone()
                        points = int(p["c"] or 0)
                        low = float(p["lo"] or 0) if p["lo"] is not None else None
                        high = float(p["hi"] or 0) if p["hi"] is not None else None
                    except Exception:
                        points = 0
                    status = "READY" if points >= 2 else "INSUFFICIENT REPLAY POINTS"

                entry = float(t.get("entry_price") or 0)
                rows.append({
                    "id": int(t.get("id") or 0),
                    "symbol": str(t.get("symbol") or ""),
                    "timestamp": t.get("timestamp"),
                    "entryPrice": entry,
                    "exitPrice": float(t.get("exit_price") or 0),
                    "pnlGbp": float(t.get("pnl_gbp") or 0),
                    "pnlPct": float(t.get("pnl_pct") or 0),
                    "reason": str(t.get("reason") or "UNKNOWN"),
                    "source": str(t.get("source") or ""),
                    "replayStatus": status,
                    "replayLink": link,
                    "replayPoints": points,
                    "replayMinPct": (((low/entry)-1)*100 if low and entry > 0 else None),
                    "replayMaxPct": (((high/entry)-1)*100 if high and entry > 0 else None),
                })

            return {
                "ok": True,
                "version": "V18.3.50",
                "since": since.isoformat(),
                "lossTrades": len(rows),
                "readyReplay": sum(1 for r in rows if r["replayStatus"] == "READY"),
                "missingReplay": sum(1 for r in rows if r["replayStatus"] != "READY"),
                "rows": rows,
                "liveTradingChanged": False,
                "note": "Read-only incident audit. Use this to identify whether recent losses have replay coverage before changing exit logic.",
            }
        finally:
            conn.close()
