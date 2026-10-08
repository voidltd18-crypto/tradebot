"""V18.3.65 — AI Exit Pilot Simulator.

Dry-runs the full V18.3.63 promotion gate without submitting orders. It records
when the current Shadow AI *would* have been allowed to perform a live EXIT and
then scores that hypothetical exit 30 open-market minutes later.

This validates the complete pilot behaviour (qualification + confidence +
confirmation + cadence + guardian-style one-at-a-time quarantine) before live
authority is ever enabled.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict, Optional
from fastapi import Request

VERSION = "V18.3.65"
POLL_SECONDS = 10
REVIEW_OPEN_MINUTES = 30
BAD_EXIT_THRESHOLD_PCT = 0.30
MIN_CONFIDENCE = 75.0
CONFIRMATIONS_REQUIRED = 2
MIN_CONFIRMATION_SECONDS = 10
MAX_SIMULATED_EXITS_PER_DAY = 10
MAX_PENDING_REVIEWS = 10

_runtime: Dict[str, Any] = {
    "version": VERSION,
    "mode": "DRY_RUN",
    "liveAuthority": False,
    "startedAt": None,
    "lastRunAt": None,
    "lastError": None,
    "marketOpen": False,
    "pilotEligible": False,
    "simulatedExitsToday": 0,
    "pendingReview": False,
    "totalSimulatedExits": 0,
    "reviewed": 0,
    "good": 0,
    "bad": 0,
    "neutral": 0,
    "accuracyPct": 0.0,
    "avgEdgePct": 0.0,
    "qualifiedForRealPilot": False,
}
_lock = threading.RLock()
_started = False
_symbol_state: Dict[str, Dict[str, Any]] = {}
_day = None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


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
        conn.execute("""CREATE TABLE IF NOT EXISTS v18365_ai_exit_pilot_sim (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            simulated_at TEXT NOT NULL,
            decision_observed_at TEXT,
            decision_confidence_pct REAL,
            exit_price REAL NOT NULL,
            pnl_pct REAL,
            open_seconds_elapsed REAL NOT NULL DEFAULT 0,
            last_tick_at TEXT,
            reviewed_at TEXT,
            review_price REAL,
            post_exit_return_pct REAL,
            decision_edge_pct REAL,
            verdict TEXT
        )""")
        conn.commit()
    finally:
        conn.close()


def _reset_day() -> None:
    global _day
    d = _today()
    with _lock:
        if _day != d:
            _day = d
            _runtime["simulatedExitsToday"] = 0
            _symbol_state.clear()


def _pilot_eligible(m) -> bool:
    try:
        fn = getattr(m, "v18361_exit_pilot_eligible", None)
        return bool(fn()) if callable(fn) else False
    except Exception:
        return False


def _latest_decision(m, symbol: str) -> Dict[str, Any]:
    try:
        fn = getattr(m, "v18360_latest_exit_decision", None)
        return dict(fn(symbol) or {}) if callable(fn) else {}
    except Exception:
        return {}


def _pending_review_count(m) -> int:
    conn = m.db_connect()
    try:
        r = conn.execute(
            "SELECT COUNT(*) c FROM v18365_ai_exit_pilot_sim WHERE verdict IS NULL"
        ).fetchone()
        return _i(r["c"])
    finally:
        conn.close()


def _pending_review(m) -> bool:
    return _pending_review_count(m) > 0


def _symbol_pending_review(m, symbol: str) -> bool:
    conn = m.db_connect()
    try:
        r = conn.execute(
            "SELECT COUNT(*) c FROM v18365_ai_exit_pilot_sim WHERE verdict IS NULL AND symbol=?",
            (str(symbol or "").upper().strip(),),
        ).fetchone()
        return _i(r["c"]) > 0
    finally:
        conn.close()


def _consider_simulated_exit(m, p: Dict[str, Any], eligible: bool, is_open: bool) -> bool:
    if not is_open or not eligible:
        return False
    if _pending_review_count(m) >= MAX_PENDING_REVIEWS:
        return False
    with _lock:
        if _i(_runtime.get("simulatedExitsToday")) >= MAX_SIMULATED_EXITS_PER_DAY:
            return False

    symbol = str(p.get("symbol") or "").upper().strip()
    if not symbol or "/" in symbol:
        return False
    if _symbol_pending_review(m, symbol):
        return False

    decision = _latest_decision(m, symbol)
    action = str(decision.get("action") or "").upper()
    confidence = _f(decision.get("decisionConfidencePct"))
    observed = str(decision.get("observedAt") or "")
    now_ts = time.time()

    st = _symbol_state.setdefault(symbol, {
        "confirmations": 0,
        "lastObservedAt": None,
        "lastSeenTs": 0.0,
        "lastAction": "NONE",
    })

    if action != "EXIT":
        st["confirmations"] = 0
        st["lastObservedAt"] = observed
        st["lastSeenTs"] = now_ts
        st["lastAction"] = action or "NONE"
        return False
    if confidence < MIN_CONFIDENCE:
        return False

    is_new = bool(observed and observed != st.get("lastObservedAt"))
    elapsed = now_ts - _f(st.get("lastSeenTs"))
    if is_new and elapsed >= MIN_CONFIRMATION_SECONDS:
        st["confirmations"] = _i(st.get("confirmations")) + 1
        st["lastObservedAt"] = observed
    st["lastSeenTs"] = now_ts
    st["lastAction"] = action

    if _i(st.get("confirmations")) < CONFIRMATIONS_REQUIRED:
        return False

    price = _f(p.get("price"))
    if price <= 0:
        return False

    conn = m.db_connect()
    try:
        conn.execute(
            """INSERT INTO v18365_ai_exit_pilot_sim
               (symbol,simulated_at,decision_observed_at,decision_confidence_pct,
                exit_price,pnl_pct,open_seconds_elapsed,last_tick_at)
               VALUES (?,?,?,?,?,?,0,?)""",
            (
                symbol, _now(), observed, confidence, price,
                _f(p.get("pnlPct")), _now(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    st["confirmations"] = 0
    with _lock:
        _runtime["simulatedExitsToday"] = _i(_runtime.get("simulatedExitsToday")) + 1

    print(
        f"{VERSION} DRY-RUN EXIT | {symbol} confidence={confidence:.1f}% "
        f"price={price:.4f} review=30_open_minutes live_orders=False",
        flush=True,
    )
    return True


def _advance_reviews(m, is_open: bool) -> None:
    conn = m.db_connect()
    try:
        rows = conn.execute(
            "SELECT * FROM v18365_ai_exit_pilot_sim WHERE verdict IS NULL ORDER BY id ASC"
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
                "UPDATE v18365_ai_exit_pilot_sim SET open_seconds_elapsed=?,last_tick_at=? WHERE id=?",
                (elapsed, now.isoformat(), _i(r.get("id"))),
            )
            if elapsed < REVIEW_OPEN_MINUTES * 60 or not is_open:
                continue
            px = _quote(m, str(r.get("symbol") or ""))
            exit_px = _f(r.get("exit_price"))
            if px <= 0 or exit_px <= 0:
                continue
            post = ((px / exit_px) - 1.0) * 100.0
            edge = -post
            if post >= BAD_EXIT_THRESHOLD_PCT:
                verdict = "BAD"
            elif post <= -0.05:
                verdict = "GOOD"
            else:
                verdict = "NEUTRAL"
            conn.execute(
                """UPDATE v18365_ai_exit_pilot_sim
                   SET reviewed_at=?,review_price=?,post_exit_return_pct=?,
                       decision_edge_pct=?,verdict=?
                   WHERE id=?""",
                (_now(), px, post, edge, verdict, _i(r.get("id"))),
            )
            print(
                f"{VERSION} DRY-RUN REVIEW | {r.get('symbol')} verdict={verdict} "
                f"post={post:+.2f}% edge={edge:+.2f}%",
                flush=True,
            )
        conn.commit()
    finally:
        conn.close()


def _stats(m) -> Dict[str, Any]:
    conn = m.db_connect()
    try:
        r = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN verdict IS NOT NULL THEN 1 ELSE 0 END) reviewed,
                      SUM(CASE WHEN verdict='GOOD' THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN verdict='BAD' THEN 1 ELSE 0 END) bad,
                      SUM(CASE WHEN verdict='NEUTRAL' THEN 1 ELSE 0 END) neutral,
                      AVG(CASE WHEN verdict IS NOT NULL THEN decision_edge_pct END) avg_edge
               FROM v18365_ai_exit_pilot_sim"""
        ).fetchone()
        total = _i(r["total"])
        reviewed = _i(r["reviewed"])
        good = _i(r["good"])
        bad = _i(r["bad"])
        neutral = _i(r["neutral"])
        directional = good + bad
        accuracy = (good / directional * 100.0) if directional else 0.0
        avg_edge = _f(r["avg_edge"])
        # This is a readiness recommendation only. It does not change authority.
        qualified = bool(
            reviewed >= 10
            and directional >= 6
            and accuracy >= 60.0
            and avg_edge > 0.10
            and bad <= 2
        )
        return {
            "totalSimulatedExits": total,
            "reviewed": reviewed,
            "good": good,
            "bad": bad,
            "neutral": neutral,
            "accuracyPct": round(accuracy, 1),
            "avgEdgePct": round(avg_edge, 4),
            "qualifiedForRealPilot": qualified,
            "readinessGate": {
                "reviewedRequired": 10,
                "directionalRequired": 6,
                "accuracyRequiredPct": 60.0,
                "avgEdgeRequiredPct": 0.10,
                "maxBad": 2,
            },
        }
    finally:
        conn.close()


def _worker(m) -> None:
    print(
        f"{VERSION} AI EXIT PILOT SIMULATOR | mode=DRY_RUN live_orders=False "
        f"confidence={MIN_CONFIDENCE:.0f}% confirmations={CONFIRMATIONS_REQUIRED} "
        f"max_per_day={MAX_SIMULATED_EXITS_PER_DAY} max_pending={MAX_PENDING_REVIEWS}",
        flush=True,
    )
    while True:
        try:
            _reset_day()
            is_open = _market_open(m)
            eligible = _pilot_eligible(m)
            _advance_reviews(m, is_open)
            if is_open and eligible and _pending_review_count(m) < MAX_PENDING_REVIEWS:
                for p in list(m.get_all_positions() or []):
                    _consider_simulated_exit(m, p, eligible, is_open)
            stats = _stats(m)
            with _lock:
                _runtime.update(stats)
                _runtime["marketOpen"] = bool(is_open)
                _runtime["pilotEligible"] = bool(eligible)
                _runtime["pendingReview"] = bool(_pending_review(m))
                _runtime["pendingReviewCount"] = _pending_review_count(m)
                _runtime["maxPendingReviews"] = MAX_PENDING_REVIEWS
                _runtime["maxSimulatedExitsPerDay"] = MAX_SIMULATED_EXITS_PER_DAY
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = None
        except Exception as exc:
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
            print(f"{VERSION} PILOT SIM ERROR | {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


def install_v18365_ai_exit_pilot_simulator(app, m) -> None:
    global _started
    _ensure_table(m)
    if not _runtime.get("startedAt"):
        _runtime["startedAt"] = _now()

    @app.get("/v18/ai-exit-pilot-simulator")
    def api_v18365_sim(request: Request):
        m.verify_api_key(request)
        stats = _stats(m)
        with _lock:
            payload = dict(_runtime)
        payload.update(stats)
        payload["liveAuthority"] = False
        payload["note"] = (
            "Dry-run only. A QUALIFIED result recommends considering the real pilot; "
            "it never enables live AI selling."
        )
        return {"ok": True, **payload}

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v18365-ai-exit-pilot-sim").start()
