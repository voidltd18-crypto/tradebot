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
    return {"sessionCount":sessions,"closedSessions":closed,
            "directLinkedSessions":direct,"pointCount":points,
            "closedTrades":trades,"readOnly":True}

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
