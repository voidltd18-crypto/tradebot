"""V18.3.52 Replay Capture Self-Diagnostics.

Observational stock replay recorder. It records live stock position price paths
for later diagnostics and persists observed sell-decision metadata separately.
It does not submit, modify, or cancel orders.
"""
from datetime import datetime, UTC
import threading
import time
from fastapi import Request


def install_v18351_live_stock_replay_capture(app, m) -> None:
    stop_flag = threading.Event()
    runtime = {
        "started": False,
        "lastCycleAt": None,
        "lastError": "",
        "cycles": 0,
        "openSessions": 0,
        "pointsWritten": 0,
        "sessionsCreated": 0,
        "sessionsClosed": 0,
        "lastPositions": [],
        "lastOpenSessionSymbols": [],
        "lastSchema": {},
        "lastCycleEvents": [],
        "positionSource": "",
        "positionError": "",
        "sessionInsertError": "",
        "pointInsertError": "",
    }

    def now_iso():
        return datetime.now(UTC).isoformat()

    def diag(event, **data):
        row = {"at": now_iso(), "event": event, **data}
        runtime["lastCycleEvents"] = (runtime.get("lastCycleEvents") or [])[-39:] + [row]
        try:
            print("V18.3.52 REPLAY DIAG | " + str(row), flush=True)
        except Exception:
            pass

    def cols(conn, table):
        try:
            return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        except Exception:
            return set()

    def ensure_tables():
        try:
            m._trade_replay_ensure_tables()
        except Exception:
            pass
        conn = m.db_connect()
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS stock_exit_decision_audit (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       session_id INTEGER,
                       closed_trade_id INTEGER,
                       symbol TEXT NOT NULL,
                       observed_at TEXT NOT NULL,
                       reason TEXT,
                       source TEXT,
                       payload TEXT
                   )"""
            )
            conn.commit()
        finally:
            conn.close()

    def insert_dynamic(conn, table, values):
        available = cols(conn, table)
        data = {k: v for k, v in values.items() if k in available}
        if not data:
            raise RuntimeError(f"{table}: no compatible columns for values={list(values)} schema={sorted(available)}")
        names = list(data)
        placeholders = ",".join(["?"] * len(names))
        cur = conn.execute(
            f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})",
            [data[n] for n in names],
        )
        return int(cur.lastrowid)

    def update_dynamic(conn, table, row_id, values):
        available = cols(conn, table)
        data = {k: v for k, v in values.items() if k in available}
        if not data:
            return
        names = list(data)
        conn.execute(
            f"UPDATE {table} SET " + ",".join([f"{n}=?" for n in names]) + " WHERE id=?",
            [data[n] for n in names] + [int(row_id)],
        )

    def open_sessions(conn):
        sc = cols(conn, "trade_replay_sessions")
        if not sc or "id" not in sc or "symbol" not in sc:
            return {}
        if "ended_at" in sc:
            rows = conn.execute(
                "SELECT * FROM trade_replay_sessions WHERE ended_at IS NULL ORDER BY id DESC"
            ).fetchall()
        else:
            rows = []
        out = {}
        for r in rows:
            d = dict(r)
            sym = str(d.get("symbol") or "").upper()
            if sym and sym not in out:
                out[sym] = d
        return out

    def latest_sell_event(symbol):
        events = list(getattr(m, "trade_events", []) or [])
        history = list(getattr(m, "trade_history", []) or [])
        for e in reversed(events + history[-500:]):
            if str(e.get("symbol") or "").upper() != symbol:
                continue
            if str(e.get("side") or "").upper() != "SELL":
                continue
            reason = str(e.get("reason") or e.get("exitReason") or e.get("message") or "UNKNOWN")
            source = str(e.get("source") or e.get("mode") or "trade_event")
            return reason, source, str(e)
        return "UNKNOWN", "position_observer", ""

    def reconcile_closed_trade(conn, symbol, entry_price, closed_at):
        try:
            rows = conn.execute(
                """SELECT * FROM closed_trades
                   WHERE symbol=? ORDER BY timestamp DESC LIMIT 12""",
                (symbol,),
            ).fetchall()
        except Exception:
            return None
        best = None
        best_score = 1e99
        for raw in rows:
            r = dict(raw)
            try:
                td = m._v6_parse_utc(r.get("timestamp"))
                cd = m._v6_parse_utc(closed_at)
                if not td or not cd:
                    continue
                seconds = abs((td - cd).total_seconds())
                if seconds > 3600:
                    continue
                ep = float(r.get("entry_price") or 0)
                diff = abs(ep-entry_price)/entry_price if ep > 0 and entry_price > 0 else 0.0
                score = seconds + diff * 600.0
                if diff <= 0.05 and score < best_score:
                    best = r
                    best_score = score
            except Exception:
                continue
        return best

    def position_snapshot():
        runtime["positionError"] = ""
        getter = getattr(m, "get_all_positions", None)
        if callable(getter):
            try:
                rows = getter() or []
                out = {}
                for p in rows:
                    sym = str(p.get("symbol") or "").upper()
                    if not sym or "/" in sym:
                        continue
                    qty = float(p.get("qty") or 0)
                    entry = float(p.get("entry") or p.get("avg_entry_price") or 0)
                    price = float(p.get("price") or p.get("current_price") or 0)
                    if qty > 0 and entry > 0 and price > 0:
                        out[sym] = {"qty": qty, "entry": entry, "price": price}
                runtime["positionSource"] = "monolith.get_all_positions"
                runtime["lastPositions"] = [{"symbol":s, **p} for s,p in out.items()]
                return out
            except Exception as exc:
                runtime["positionError"] = f"get_all_positions: {type(exc).__name__}: {exc}"
                diag("POSITION_SOURCE_ERROR", source="monolith.get_all_positions", error=runtime["positionError"])

        client = getattr(m, "trading_client", None)
        out = {}
        if client is None:
            runtime["positionSource"] = "none"
            runtime["positionError"] = (runtime.get("positionError") or "") + " | trading_client missing"
            return out
        try:
            raw = list(client.get_all_positions() or [])
            for p in raw:
                sym = str(getattr(p, "symbol", "") or "").upper()
                if not sym or "/" in sym:
                    continue
                qty = float(getattr(p, "qty", 0) or 0)
                entry = float(getattr(p, "avg_entry_price", 0) or 0)
                price = float(getattr(p, "current_price", 0) or 0)
                if qty > 0 and entry > 0 and price > 0:
                    out[sym] = {"qty": qty, "entry": entry, "price": price}
            runtime["positionSource"] = "trading_client.get_all_positions"
            runtime["lastPositions"] = [{"symbol":s, **p} for s,p in out.items()]
        except Exception as exc:
            runtime["positionSource"] = "trading_client.get_all_positions"
            runtime["positionError"] = f"trading_client: {type(exc).__name__}: {exc}"
            diag("POSITION_SOURCE_ERROR", source="trading_client.get_all_positions", error=runtime["positionError"])
        return out

    def write_point(conn, session_id, price, symbol=""):
        pc = cols(conn, "trade_replay_points")
        values = {"session_id": int(session_id), "symbol": str(symbol or "").upper(), "price": float(price)}
        stamp = now_iso()
        for candidate in ("timestamp", "time", "recorded_at", "created_at", "observed_at", "sampled_at", "captured_at", "ts"):
            if candidate in pc:
                values[candidate] = stamp
                break
        try:
            point_id = insert_dynamic(conn, "trade_replay_points", values)
            if point_id is not None:
                runtime["pointsWritten"] += 1
                runtime["pointInsertError"] = ""
                diag("POINT_WRITTEN", symbol=symbol, sessionId=int(session_id), pointId=point_id, price=float(price))
        except Exception as exc:
            runtime["pointInsertError"] = f"{type(exc).__name__}: {exc}"
            diag("POINT_INSERT_ERROR", symbol=symbol, sessionId=int(session_id), error=runtime["pointInsertError"], schema=sorted(pc))
            raise

    def cycle():
        ensure_tables()
        positions = position_snapshot()
        conn = m.db_connect()
        try:
            session_schema = sorted(cols(conn, "trade_replay_sessions"))
            point_schema = sorted(cols(conn, "trade_replay_points"))
            runtime["lastSchema"] = {"trade_replay_sessions": session_schema, "trade_replay_points": point_schema}
            active = open_sessions(conn)
            runtime["lastOpenSessionSymbols"] = sorted(active)
            diag("CYCLE", positions=sorted(positions), activeSessions=sorted(active), source=runtime.get("positionSource"),
                 positionError=runtime.get("positionError"), sessionSchema=session_schema, pointSchema=point_schema)

            for sym, p in positions.items():
                sess = active.get(sym)
                if not sess:
                    try:
                        sid = insert_dynamic(
                            conn,
                            "trade_replay_sessions",
                            {
                                "symbol": sym,
                                "started_at": now_iso(),
                                "entry_price": p["entry"],
                                "qty": p["qty"],
                            },
                        )
                        runtime["sessionInsertError"] = ""
                    except Exception as exc:
                        runtime["sessionInsertError"] = f"{type(exc).__name__}: {exc}"
                        diag("SESSION_INSERT_ERROR", symbol=sym, error=runtime["sessionInsertError"], schema=session_schema, position=p)
                        raise
                    if sid is not None:
                        runtime["sessionsCreated"] += 1
                        sess = {"id": sid, "symbol": sym, "entry_price": p["entry"], "qty": p["qty"]}
                        active[sym] = sess
                        diag("SESSION_CREATED", symbol=sym, sessionId=sid, entry=p["entry"], qty=p["qty"])
                if sess and sess.get("id"):
                    write_point(conn, int(sess["id"]), p["price"], sym)

            for sym, sess in list(active.items()):
                if sym in positions:
                    continue
                sid = int(sess.get("id") or 0)
                if sid <= 0:
                    continue
                closed_at = now_iso()
                entry = float(sess.get("entry_price") or 0)
                closed_trade = reconcile_closed_trade(conn, sym, entry, closed_at)
                closed_trade_id = int(closed_trade.get("id") or 0) if closed_trade else None
                update_dynamic(
                    conn,
                    "trade_replay_sessions",
                    sid,
                    {"ended_at": closed_at, "closed_trade_id": closed_trade_id},
                )
                reason, source, payload = latest_sell_event(sym)
                conn.execute(
                    """INSERT INTO stock_exit_decision_audit
                       (session_id,closed_trade_id,symbol,observed_at,reason,source,payload)
                       VALUES (?,?,?,?,?,?,?)""",
                    (sid, closed_trade_id, sym, closed_at, reason, source, payload),
                )
                runtime["sessionsClosed"] += 1
                diag("SESSION_CLOSED", symbol=sym, sessionId=sid, closedTradeId=closed_trade_id, reason=reason, source=source)

            conn.commit()
            runtime["openSessions"] = len(positions)
            runtime["cycles"] += 1
            runtime["lastCycleAt"] = now_iso()
            runtime["lastError"] = ""
        finally:
            conn.close()

    def worker():
        runtime["started"] = True
        while not stop_flag.is_set():
            try:
                cycle()
            except Exception as exc:
                runtime["lastError"] = f"{type(exc).__name__}: {exc}"
                diag("CYCLE_ERROR", error=runtime["lastError"])
            stop_flag.wait(10)

    @app.get("/v18/replay-capture-status")
    def api_replay_capture_status(request: Request):
        m.verify_api_key(request)
        ensure_tables()
        conn = m.db_connect()
        try:
            sessions = conn.execute("SELECT COUNT(*) c FROM trade_replay_sessions").fetchone()["c"]
            points = conn.execute("SELECT COUNT(*) c FROM trade_replay_points").fetchone()["c"]
            exits = conn.execute("SELECT COUNT(*) c FROM stock_exit_decision_audit").fetchone()["c"]
        finally:
            conn.close()
        return {
            "ok": True,
            "version": "V18.3.53",
            "recorder": dict(runtime),
            "database": {"sessions": int(sessions or 0), "points": int(points or 0), "exitDecisionAudits": int(exits or 0)},
            "liveTradingChanged": False,
        }

    ensure_tables()
    diag("RECORDER_INSTALL", intervalSec=10)
    thread = threading.Thread(target=worker, name="v18352-stock-replay-diagnostics", daemon=True)
    thread.start()
