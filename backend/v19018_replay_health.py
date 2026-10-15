"""V19.0.18 passive replay health telemetry, read-only and aggregated.

Samples DB metadata on a daemon thread. Does not invoke trade APIs, orders,
simulation or authenticated API endpoints.
"""
import threading
from datetime import datetime, timezone

def replay_health_snapshot(conn):
    def safe_count(sql):
        try:
            row=conn.execute(sql).fetchone()
            return int(row[0]) if row else 0
        except Exception:
            return None
    sessions=safe_count("SELECT COUNT(*) FROM trade_replay_sessions")
    closed=safe_count("SELECT COUNT(*) FROM trade_replay_sessions WHERE ended_at IS NOT NULL")
    direct=safe_count("SELECT COUNT(*) FROM trade_replay_sessions WHERE closed_trade_id IS NOT NULL")
    points=safe_count("SELECT COUNT(*) FROM trade_replay_points")
    trades=safe_count("SELECT COUNT(*) FROM closed_trades")
    # IDs alone are not evidence of a correct trade-to-session match.
    # Validate foreign existence, symbol agreement and close-time proximity.
    linked_valid=0
    linked_missing=0
    linked_symbol_mismatch=0
    linked_time_mismatch=0
    linked_time_unknown=0
    try:
        from datetime import datetime
        rows=conn.execute("""
            SELECT s.symbol session_symbol,s.ended_at session_end,
                   t.id trade_id,t.symbol trade_symbol,t.timestamp trade_end
            FROM trade_replay_sessions s
            LEFT JOIN closed_trades t ON t.id=s.closed_trade_id
            WHERE s.closed_trade_id IS NOT NULL
        """).fetchall()
        def parse_stamp(value):
            try:
                d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
                return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
            except (ValueError,TypeError):
                return None
        for row in rows:
            sym,ended,tid,trade_sym,trade_end=row
            if tid is None:
                linked_missing+=1
            elif str(sym or "").upper()!=str(trade_sym or "").upper():
                linked_symbol_mismatch+=1
            else:
                st,tt=parse_stamp(ended),parse_stamp(trade_end)
                if st is None or tt is None:
                    linked_time_unknown+=1
                elif abs((st-tt).total_seconds())>3600:
                    linked_time_mismatch+=1
                else:
                    linked_valid+=1
    except Exception:
        linked_valid=linked_missing=linked_symbol_mismatch=linked_time_mismatch=linked_time_unknown=None
    return {"sessionCount":sessions,"closedSessions":closed,
            "directLinkedSessions":direct,"pointCount":points,
            "closedTrades":trades,"linkedWithin1hAndSameSymbol":linked_valid,\n            "linkedMissingTrade":linked_missing,\n            "linkedSymbolMismatch":linked_symbol_mismatch,\n            "linkedOver1hApart":linked_time_mismatch,\n            "linkedUnknownTime":linked_time_unknown,\n            "readOnly":True}

def install_v19018_replay_health(app,m):
    stop=threading.Event()
    def run():
        # Run one pass soon after startup, then every 30 minutes.
        if stop.wait(15):return
        while not stop.is_set():
            conn=None
            try:
                conn=m.db_connect()
                snapshot=replay_health_snapshot(conn)
                fields=" ".join(f"{k}={v}" for k,v in snapshot.items())
                print("V19 REPLAY HEALTH | "+fields,flush=True)
            except Exception as e:
                print("V19 REPLAY HEALTH ERROR | "+type(e).__name__,flush=True)
            finally:
                if conn is not None:
                    try:conn.close()
                    except Exception:pass
            stop.wait(1800)
    threading.Thread(target=run,daemon=True,name="v19018-replay-health").start()
