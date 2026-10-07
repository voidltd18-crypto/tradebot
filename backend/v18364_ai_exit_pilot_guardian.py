"""V18.3.64 — AI Exit Pilot Guardian.

Safety supervisor for the future V18.3.63 live AI-exit pilot.

Whenever an AI pilot exit is actually submitted, the guardian records it and
blocks further AI-driven live exits until that exit has been reviewed after 30
open-market minutes. If price rises materially after the AI sold, the guardian
suspends future AI live exits for manual review. Good/neutral reviews clear the
hold automatically.

This module does not place orders. Hard stops and existing account protections
remain outside and above this guardian.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict, Optional

VERSION = "V18.3.64"
POLL_SECONDS = 10
REVIEW_OPEN_MINUTES = 30
BAD_EXIT_THRESHOLD_PCT = 0.30

_runtime: Dict[str, Any] = {
    "version": VERSION,
    "state": "READY",
    "suspended": False,
    "suspensionReason": None,
    "pendingReview": False,
    "pendingExitId": None,
    "lastReview": None,
    "lastRunAt": None,
    "lastError": None,
}
_lock = threading.RLock()
_started = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return d


def _i(v: Any, d: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return d


def _dt(v: Any) -> Optional[datetime]:
    try:
        raw = str(v or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        x = datetime.fromisoformat(raw)
        if x.tzinfo is None:
            x = x.replace(tzinfo=UTC)
        return x.astimezone(UTC)
    except Exception:
        return None


def _market_open(m) -> bool:
    try:
        return bool(getattr(m.trading_client.get_clock(), "is_open", False))
    except Exception:
        try:
            return bool(m.get_effective_market_status_payload().get("isOpen"))
        except Exception:
            return False


def _quote(m, symbol: str) -> float:
    try:
        q = m.get_quote(symbol)
        return _f(q.get("mid") or q.get("last") or q.get("price"))
    except Exception:
        return 0.0


def _ensure_table(m) -> None:
    conn = m.db_connect()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS v18364_ai_exit_pilot_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            exit_price REAL NOT NULL,
            pnl_pct REAL,
            confidence_pct REAL,
            reason TEXT,
            open_seconds_elapsed REAL NOT NULL DEFAULT 0,
            last_tick_at TEXT,
            reviewed_at TEXT,
            review_price REAL,
            post_exit_return_pct REAL,
            verdict TEXT,
            suspended INTEGER NOT NULL DEFAULT 0
        )""")
        conn.commit()
    finally:
        conn.close()


def _load_state(m) -> None:
    conn = m.db_connect()
    try:
        pending = conn.execute(
            """SELECT * FROM v18364_ai_exit_pilot_reviews
               WHERE verdict IS NULL ORDER BY id ASC LIMIT 1"""
        ).fetchone()
        bad = conn.execute(
            """SELECT * FROM v18364_ai_exit_pilot_reviews
               WHERE suspended=1 ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        with _lock:
            if bad:
                _runtime["suspended"] = True
                _runtime["state"] = "SUSPENDED"
                _runtime["suspensionReason"] = (
                    f"AI exit {bad['symbol']} was followed by "
                    f"{_f(bad['post_exit_return_pct']):+.2f}% in 30 open-market minutes"
                )
            if pending:
                _runtime["pendingReview"] = True
                _runtime["pendingExitId"] = _i(pending["id"])
                if not _runtime["suspended"]:
                    _runtime["state"] = "REVIEW_HOLD"
            elif not _runtime["suspended"]:
                _runtime["pendingReview"] = False
                _runtime["pendingExitId"] = None
                _runtime["state"] = "READY"
    finally:
        conn.close()


def guardian_allows_live_exit(m) -> Dict[str, Any]:
    _load_state(m)
    with _lock:
        if _runtime.get("suspended"):
            return {
                "allowed": False,
                "reason": str(_runtime.get("suspensionReason") or "AI pilot guardian suspended"),
            }
        if _runtime.get("pendingReview"):
            return {
                "allowed": False,
                "reason": "previous AI pilot exit is awaiting 30-minute guardian review",
            }
    return {"allowed": True, "reason": "guardian ready"}


def record_exit(m, symbol: str, price: float, pnl_pct: float = 0.0, confidence_pct: float = 0.0, reason: str = "") -> int:
    sym = str(symbol or "").upper().strip()
    px = _f(price)
    if not sym or px <= 0:
        return 0
    conn = m.db_connect()
    try:
        cur = conn.execute(
            """INSERT INTO v18364_ai_exit_pilot_reviews
               (symbol,submitted_at,exit_price,pnl_pct,confidence_pct,reason,
                open_seconds_elapsed,last_tick_at,suspended)
               VALUES (?,?,?,?,?,?,0,?,0)""",
            (sym, _now(), px, _f(pnl_pct), _f(confidence_pct), str(reason or ""), _now()),
        )
        conn.commit()
        rid = _i(cur.lastrowid)
    finally:
        conn.close()
    _load_state(m)
    print(
        f"{VERSION} PILOT EXIT RECORDED | id={rid} symbol={sym} price={px:.4f} review=30_open_minutes",
        flush=True,
    )
    return rid


def _advance_and_review(m) -> None:
    is_open = _market_open(m)
    conn = m.db_connect()
    try:
        rows = conn.execute(
            """SELECT * FROM v18364_ai_exit_pilot_reviews
               WHERE verdict IS NULL ORDER BY id ASC"""
        ).fetchall()
        now = datetime.now(UTC)
        for raw in rows:
            r = dict(raw)
            last = _dt(r.get("last_tick_at")) or now
            delta = max(0.0, min(60.0, (now - last).total_seconds()))
            elapsed = _f(r.get("open_seconds_elapsed"))
            if is_open:
                elapsed += delta
            conn.execute(
                "UPDATE v18364_ai_exit_pilot_reviews SET open_seconds_elapsed=?,last_tick_at=? WHERE id=?",
                (elapsed, now.isoformat(), _i(r.get("id"))),
            )
            if elapsed < REVIEW_OPEN_MINUTES * 60 or not is_open:
                continue
            review_price = _quote(m, str(r.get("symbol") or ""))
            exit_price = _f(r.get("exit_price"))
            if review_price <= 0 or exit_price <= 0:
                continue
            post = ((review_price / exit_price) - 1.0) * 100.0
            # An EXIT is good when price subsequently falls, bad when it rises
            # materially. Small moves are treated as neutral noise.
            if post >= BAD_EXIT_THRESHOLD_PCT:
                verdict = "BAD"
                suspended = 1
            elif post <= -0.05:
                verdict = "GOOD"
                suspended = 0
            else:
                verdict = "NEUTRAL"
                suspended = 0
            conn.execute(
                """UPDATE v18364_ai_exit_pilot_reviews
                   SET reviewed_at=?,review_price=?,post_exit_return_pct=?,
                       verdict=?,suspended=?
                   WHERE id=?""",
                (_now(), review_price, post, verdict, suspended, _i(r.get("id"))),
            )
            print(
                f"{VERSION} PILOT EXIT REVIEW | id={_i(r.get('id'))} "
                f"symbol={r.get('symbol')} verdict={verdict} post={post:+.2f}% "
                f"suspended={bool(suspended)}",
                flush=True,
            )
        conn.commit()
    finally:
        conn.close()
    _load_state(m)

    conn = m.db_connect()
    try:
        last = conn.execute(
            """SELECT id,symbol,reviewed_at,exit_price,review_price,
                      post_exit_return_pct,verdict,suspended
               FROM v18364_ai_exit_pilot_reviews
               WHERE verdict IS NOT NULL ORDER BY id DESC LIMIT 1"""
        ).fetchone()
        if last:
            with _lock:
                _runtime["lastReview"] = dict(last)
    finally:
        conn.close()


def _worker(m) -> None:
    print(
        f"{VERSION} AI EXIT PILOT GUARDIAN | review={REVIEW_OPEN_MINUTES}m "
        f"bad_exit_threshold=+{BAD_EXIT_THRESHOLD_PCT:.2f}% live_orders=False",
        flush=True,
    )
    while True:
        try:
            _advance_and_review(m)
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = None
        except Exception as exc:
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
            print(f"{VERSION} GUARDIAN ERROR | {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


def install_v18364_ai_exit_pilot_guardian(app, m) -> None:
    global _started
    _ensure_table(m)
    _load_state(m)

    m.v18364_ai_exit_guardian_check = lambda: guardian_allows_live_exit(m)
    m.v18364_record_ai_exit = lambda symbol, price, pnl_pct=0.0, confidence_pct=0.0, reason="": record_exit(
        m, symbol, price, pnl_pct, confidence_pct, reason
    )

    @app.get("/v18/ai-exit-pilot-guardian")
    def api_v18364_guardian(request: m.Request):
        m.verify_api_key(request)
        _load_state(m)
        with _lock:
            payload = dict(_runtime)
        payload["reviewOpenMinutes"] = REVIEW_OPEN_MINUTES
        payload["badExitThresholdPct"] = BAD_EXIT_THRESHOLD_PCT
        payload["note"] = (
            "A live AI pilot exit pauses further AI exits until reviewed. "
            "A materially bad exit suspends AI live authority for manual review."
        )
        return {"ok": True, **payload}

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v18364-ai-exit-guardian").start()
