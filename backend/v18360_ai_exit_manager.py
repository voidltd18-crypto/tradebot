"""V18.3.60 — Stock AI Exit Manager (Shadow).

Research-only autonomous position manager. It observes live stock positions,
forms HOLD / PROTECT / EXIT recommendations, records the evidence and exposes
it to the UI. It never submits, cancels or modifies an order.

The hard safety layer in the monolith remains authoritative.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict, List

VERSION = "V18.3.60"
INTERVAL_SECONDS = 10
MIN_LOG_SECONDS = 45
_runtime: Dict[str, Any] = {
    "version": VERSION,
    "mode": "SHADOW",
    "liveAuthority": False,
    "startedAt": None,
    "lastRunAt": None,
    "lastError": None,
    "cycles": 0,
    "positionsSeen": 0,
    "decisions": {},
}
_lock = threading.RLock()
_started = False
_last_logged: Dict[str, Dict[str, Any]] = {}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _scan_for(m, symbol: str) -> Dict[str, Any]:
    try:
        for row in list(getattr(m, "latest_scans", []) or []):
            if str(row.get("symbol") or "").upper() == symbol:
                return dict(row)
    except Exception:
        pass
    return {}


def _market_regime(m) -> str:
    try:
        status = getattr(m, "latest_status", {}) or {}
        for value in (
            status.get("marketRegime"),
            (status.get("ai") or {}).get("marketRegime") if isinstance(status.get("ai"), dict) else None,
            status.get("regime"),
        ):
            if value:
                return str(value)
    except Exception:
        pass
    return "UNKNOWN"


def _history_edge(m, symbol: str) -> Dict[str, Any]:
    try:
        row = dict((getattr(m, "stock_memory", {}) or {}).get(symbol) or {})
        wins = _i(row.get("wins"))
        losses = _i(row.get("losses"))
        trades = wins + losses
        win_rate = (wins / trades) if trades else 0.0
        return {
            "trades": trades,
            "winRate": win_rate,
            "pnl": _f(row.get("pnl") or row.get("totalPnl") or row.get("profit")),
        }
    except Exception:
        return {"trades": 0, "winRate": 0.0, "pnl": 0.0}


def _decision(m, p: Dict[str, Any]) -> Dict[str, Any]:
    symbol = str(p.get("symbol") or "").upper().strip()
    entry = _f(p.get("entry"))
    price = _f(p.get("price"))
    highest = _f(p.get("highest"))
    pnl_pct = _f(p.get("pnlPct"))
    held = _i(p.get("minutesSinceBuy"), 999999)
    peak_pct = ((highest / entry) - 1.0) * 100.0 if entry > 0 and highest > 0 else pnl_pct
    giveback = max(0.0, peak_pct - pnl_pct)
    try:
        momentum = _f(m.compute_short_momentum(symbol, price))
    except Exception:
        momentum = 0.0

    scan = _scan_for(m, symbol)
    confidence = _f(scan.get("confidence"))
    quality = _f(scan.get("quality_score") or scan.get("qualityScore"))
    spread = _f(p.get("spread") or scan.get("spread"))
    sniper = bool(scan.get("sniper_pass"))
    aplus = bool(scan.get("a_plus_pass"))
    hist = _history_edge(m, symbol)
    regime = _market_regime(m)

    hold = 50.0
    exit_pressure = 0.0
    reasons: List[str] = []

    # Thesis strength: live direction matters more than static age.
    if momentum > 0.0015:
        hold += 18; reasons.append("short momentum strengthening")
    elif momentum > 0:
        hold += 8; reasons.append("short momentum positive")
    elif momentum < -0.003:
        exit_pressure += 22; reasons.append("short momentum materially negative")
    elif momentum < -0.001:
        exit_pressure += 10; reasons.append("short momentum fading")

    if pnl_pct > 1.25:
        hold += 14; reasons.append("position is a meaningful winner")
    elif pnl_pct > 0.25:
        hold += 8; reasons.append("position remains green")
    elif pnl_pct < -1.0:
        exit_pressure += 20; reasons.append("loss is becoming material")
    elif pnl_pct < -0.45:
        exit_pressure += 9; reasons.append("position is under entry")

    # Protect winners only after the trade has proved itself.
    if peak_pct >= 1.0:
        hold += 8
        if giveback >= 0.75:
            exit_pressure += 24; reasons.append("winner has given back a material part of its peak")
        elif giveback >= 0.40:
            exit_pressure += 10; reasons.append("winner is giving back")

    # A strong live setup gets patience; weak current evidence does not force a sale alone.
    if aplus and sniper:
        hold += 12; reasons.append("fresh Sniper + A+ evidence still agrees")
    elif confidence >= 0.70 and quality >= 0.02:
        hold += 6; reasons.append("fresh scan quality remains supportive")

    if spread > 0.012:
        exit_pressure += 4; reasons.append("spread/liquidity quality deteriorated")

    if hist.get("trades", 0) >= 5:
        if hist.get("winRate", 0.0) >= 0.55 and hist.get("pnl", 0.0) > 0:
            hold += 6; reasons.append("symbol history is supportive")
        elif hist.get("winRate", 0.0) <= 0.35 and hist.get("pnl", 0.0) < 0:
            exit_pressure += 6; reasons.append("symbol history is weak")

    # Time is context, never the reason by itself.
    if held >= 90 and pnl_pct <= 0 and momentum < 0:
        exit_pressure += 5; reasons.append("mature trade is red and still weakening")
    if held >= 90 and pnl_pct > 0 and momentum >= 0:
        hold += 5; reasons.append("mature winner is still behaving")

    net = hold - exit_pressure
    if exit_pressure >= 34 and net < 42:
        action = "EXIT"
    elif peak_pct >= 0.75 and giveback >= 0.35 and pnl_pct > 0:
        action = "PROTECT"
    else:
        action = "HOLD"

    # Confidence is about decisiveness, not probability of profit.
    confidence_pct = min(99.0, max(50.0, 50.0 + abs(net - 50.0) * 1.15))
    if action == "EXIT":
        confidence_pct = min(99.0, max(confidence_pct, 55.0 + min(35.0, exit_pressure)))

    return {
        "symbol": symbol,
        "action": action,
        "decisionConfidencePct": round(confidence_pct, 1),
        "holdScore": round(hold, 2),
        "exitPressure": round(exit_pressure, 2),
        "pnlPct": round(pnl_pct, 4),
        "peakPct": round(peak_pct, 4),
        "givebackPct": round(giveback, 4),
        "momentum": round(momentum, 6),
        "heldMinutes": held,
        "price": round(price, 6),
        "entry": round(entry, 6),
        "marketValueGbp": round(_f(p.get("marketValueGbp")), 4),
        "scanConfidence": round(confidence, 4),
        "scanQuality": round(quality, 6),
        "sniperPass": sniper,
        "aPlusPass": aplus,
        "marketRegime": regime,
        "historyTrades": hist.get("trades", 0),
        "historyWinRatePct": round(hist.get("winRate", 0.0) * 100.0, 1),
        "reasons": reasons[:6],
        "shadowOnly": True,
        "liveAuthority": False,
        "observedAt": _now(),
    }


def _ensure_table(m) -> None:
    conn = m.db_connect()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS v18360_ai_exit_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            observed_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence_pct REAL,
            price REAL,
            entry_price REAL,
            pnl_pct REAL,
            peak_pct REAL,
            giveback_pct REAL,
            momentum REAL,
            held_minutes INTEGER,
            market_regime TEXT,
            features_json TEXT,
            reasons_json TEXT,
            live_authority INTEGER NOT NULL DEFAULT 0
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v18360_symbol_time ON v18360_ai_exit_decisions(symbol, observed_at)")
        conn.commit()
    finally:
        conn.close()


def _record(m, row: Dict[str, Any]) -> None:
    symbol = row["symbol"]
    now_ts = time.time()
    prev = _last_logged.get(symbol) or {}
    changed = prev.get("action") != row.get("action")
    due = now_ts - _f(prev.get("ts")) >= MIN_LOG_SECONDS
    if not changed and not due:
        return
    conn = m.db_connect()
    try:
        features = {k: row.get(k) for k in (
            "holdScore","exitPressure","scanConfidence","scanQuality","sniperPass",
            "aPlusPass","historyTrades","historyWinRatePct","marketValueGbp"
        )}
        conn.execute("""INSERT INTO v18360_ai_exit_decisions
            (observed_at,symbol,action,confidence_pct,price,entry_price,pnl_pct,peak_pct,
             giveback_pct,momentum,held_minutes,market_regime,features_json,reasons_json,live_authority)
             VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
            (row["observedAt"], symbol, row["action"], row["decisionConfidencePct"],
             row["price"], row["entry"], row["pnlPct"], row["peakPct"], row["givebackPct"],
             row["momentum"], row["heldMinutes"], row["marketRegime"],
             json.dumps(features,separators=(",",":")),
             json.dumps(row.get("reasons") or [],separators=(",",":"))))
        conn.commit()
    finally:
        conn.close()
    _last_logged[symbol] = {"action": row.get("action"), "ts": now_ts}


def _worker(m) -> None:
    print(f"{VERSION} AI EXIT MANAGER | mode=SHADOW live_authority=False interval={INTERVAL_SECONDS}s hard_safety=UNCHANGED", flush=True)
    while True:
        try:
            positions = [p for p in list(m.get_all_positions() or []) if "/" not in str(p.get("symbol") or "")]
            decisions = {}
            for p in positions:
                row = _decision(m, p)
                decisions[row["symbol"]] = row
                _record(m, row)
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = None
                _runtime["cycles"] = int(_runtime.get("cycles") or 0) + 1
                _runtime["positionsSeen"] = len(positions)
                _runtime["decisions"] = decisions
        except Exception as exc:
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
            print(f"{VERSION} AI EXIT MANAGER ERROR | {type(exc).__name__}: {exc}", flush=True)
        time.sleep(INTERVAL_SECONDS)


def _history(m, limit: int = 100) -> List[Dict[str, Any]]:
    conn = m.db_connect()
    try:
        rows = conn.execute("""SELECT id,observed_at,symbol,action,confidence_pct,price,entry_price,
            pnl_pct,peak_pct,giveback_pct,momentum,held_minutes,market_regime,reasons_json
            FROM v18360_ai_exit_decisions ORDER BY id DESC LIMIT ?""", (max(1,min(int(limit),500)),)).fetchall()
        out=[]
        for r in rows:
            d=dict(r)
            try: d["reasons"]=json.loads(d.pop("reasons_json") or "[]")
            except Exception: d["reasons"]=[]
            out.append(d)
        return out
    finally:
        conn.close()


def install_v18360_ai_exit_manager(app, m) -> None:
    global _started
    _ensure_table(m)
    if not _runtime.get("startedAt"):
        _runtime["startedAt"] = _now()

    @app.get("/v18/ai-exit-manager")
    def api_v18360_ai_exit_manager(request: m.Request, limit: int = 60):
        m.verify_api_key(request)
        with _lock:
            payload = dict(_runtime)
            payload["decisions"] = list((_runtime.get("decisions") or {}).values())
        payload["history"] = _history(m, limit)
        payload["note"] = "Shadow-only: AI recommendations are recorded but cannot submit orders."
        return {"ok": True, **payload}

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v18360-ai-exit-shadow").start()
