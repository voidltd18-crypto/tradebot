"""V18.3.66 — Autonomous AI Exit Promotion Controller.

Coordinates the complete stock AI-exit lifecycle:
Shadow evidence -> dry-run simulator -> guarded live pilot -> trusted pilot.

This controller never submits orders. It only exposes promotion readiness and
a bounded live-exit daily cap to V18.3.63. Hard safety, Piggy protection,
broker/PDT restrictions and the V18.3.64 Guardian remain authoritative.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict

VERSION = "V18.3.66"
POLL_SECONDS = 30

_runtime: Dict[str, Any] = {
    "version": VERSION,
    "state": "EVIDENCE",
    "liveAuthority": False,
    "scorerQualified": False,
    "simulatorQualified": False,
    "guardianSuspended": False,
    "guardianPendingReview": False,
    "liveReviewed": 0,
    "liveGood": 0,
    "liveBad": 0,
    "liveNeutral": 0,
    "liveAccuracyPct": 0.0,
    "liveAvgEdgePct": 0.0,
    "dailyAiExitCap": 1,
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


def _table_exists(conn, name: str) -> bool:
    try:
        return bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (name,),
        ).fetchone())
    except Exception:
        return False


def _scorer_qualified(m) -> bool:
    try:
        fn = getattr(m, "v18361_exit_pilot_eligible", None)
        return bool(fn()) if callable(fn) else False
    except Exception:
        return False


def _simulator_stats(m) -> Dict[str, Any]:
    conn = m.db_connect()
    try:
        if not _table_exists(conn, "v18365_ai_exit_pilot_sim"):
            return {"qualified": False}
        r = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN verdict IS NOT NULL THEN 1 ELSE 0 END) reviewed,
                      SUM(CASE WHEN verdict='GOOD' THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN verdict='BAD' THEN 1 ELSE 0 END) bad,
                      SUM(CASE WHEN verdict='NEUTRAL' THEN 1 ELSE 0 END) neutral,
                      AVG(CASE WHEN verdict IS NOT NULL THEN decision_edge_pct END) avg_edge
               FROM v18365_ai_exit_pilot_sim"""
        ).fetchone()
        reviewed = _i(r["reviewed"])
        good = _i(r["good"])
        bad = _i(r["bad"])
        neutral = _i(r["neutral"])
        directional = good + bad
        accuracy = (good / directional * 100.0) if directional else 0.0
        avg_edge = _f(r["avg_edge"])
        qualified = bool(
            reviewed >= 10 and directional >= 6 and accuracy >= 60.0
            and avg_edge > 0.10 and bad <= 2
        )
        return {
            "qualified": qualified,
            "total": _i(r["total"]),
            "reviewed": reviewed,
            "good": good,
            "bad": bad,
            "neutral": neutral,
            "accuracyPct": round(accuracy, 1),
            "avgEdgePct": round(avg_edge, 4),
        }
    finally:
        conn.close()


def _guardian_stats(m) -> Dict[str, Any]:
    conn = m.db_connect()
    try:
        if not _table_exists(conn, "v18364_ai_exit_pilot_reviews"):
            return {
                "suspended": False, "pending": False, "reviewed": 0,
                "good": 0, "bad": 0, "neutral": 0, "accuracyPct": 0.0,
                "avgEdgePct": 0.0,
            }
        pending = bool(conn.execute(
            "SELECT 1 FROM v18364_ai_exit_pilot_reviews WHERE verdict IS NULL LIMIT 1"
        ).fetchone())
        suspended = bool(conn.execute(
            "SELECT 1 FROM v18364_ai_exit_pilot_reviews WHERE suspended=1 ORDER BY id DESC LIMIT 1"
        ).fetchone())
        r = conn.execute(
            """SELECT COUNT(*) reviewed,
                      SUM(CASE WHEN verdict='GOOD' THEN 1 ELSE 0 END) good,
                      SUM(CASE WHEN verdict='BAD' THEN 1 ELSE 0 END) bad,
                      SUM(CASE WHEN verdict='NEUTRAL' THEN 1 ELSE 0 END) neutral,
                      AVG(CASE WHEN verdict IS NOT NULL THEN -post_exit_return_pct END) avg_edge
               FROM v18364_ai_exit_pilot_reviews
               WHERE verdict IS NOT NULL"""
        ).fetchone()
        reviewed = _i(r["reviewed"])
        good = _i(r["good"])
        bad = _i(r["bad"])
        neutral = _i(r["neutral"])
        directional = good + bad
        accuracy = (good / directional * 100.0) if directional else 0.0
        return {
            "suspended": suspended,
            "pending": pending,
            "reviewed": reviewed,
            "good": good,
            "bad": bad,
            "neutral": neutral,
            "accuracyPct": round(accuracy, 1),
            "avgEdgePct": round(_f(r["avg_edge"]), 4),
        }
    finally:
        conn.close()


def _evaluate(m) -> Dict[str, Any]:
    scorer = _scorer_qualified(m)
    sim = _simulator_stats(m)
    live = _guardian_stats(m)

    cap = 1
    state = "EVIDENCE"
    if scorer:
        state = "SIMULATION"
    if scorer and sim.get("qualified"):
        state = "PILOT_READY"

    # Graduated live authority remains conservative and evidence-bound.
    if live.get("reviewed", 0) >= 10:
        directional = _i(live.get("good")) + _i(live.get("bad"))
        if (
            directional >= 6
            and _f(live.get("accuracyPct")) >= 60.0
            and _f(live.get("avgEdgePct")) > 0.10
            and _i(live.get("bad")) <= 2
        ):
            state = "TRUSTED_PILOT"
            cap = 2

    if live.get("reviewed", 0) >= 25:
        directional = _i(live.get("good")) + _i(live.get("bad"))
        if (
            directional >= 15
            and _f(live.get("accuracyPct")) >= 65.0
            and _f(live.get("avgEdgePct")) > 0.15
            and _i(live.get("bad")) <= 4
        ):
            state = "GRADUATED"
            cap = 4

    if live.get("pending"):
        state = "REVIEW_HOLD"
    if live.get("suspended"):
        state = "SUSPENDED"
        cap = 0

    return {
        "state": state,
        "scorerQualified": scorer,
        "simulatorQualified": bool(sim.get("qualified")),
        "simulator": sim,
        "guardianSuspended": bool(live.get("suspended")),
        "guardianPendingReview": bool(live.get("pending")),
        "liveReviewed": _i(live.get("reviewed")),
        "liveGood": _i(live.get("good")),
        "liveBad": _i(live.get("bad")),
        "liveNeutral": _i(live.get("neutral")),
        "liveAccuracyPct": _f(live.get("accuracyPct")),
        "liveAvgEdgePct": _f(live.get("avgEdgePct")),
        "dailyAiExitCap": cap,
        "promotionReady": bool(
            scorer and sim.get("qualified")
            and not live.get("pending") and not live.get("suspended")
        ),
    }


def promotion_status(m) -> Dict[str, Any]:
    result = _evaluate(m)
    with _lock:
        _runtime.update(result)
        _runtime["lastRunAt"] = _now()
        _runtime["lastError"] = None
        return dict(_runtime)


def live_preflight(m) -> Dict[str, Any]:
    s = promotion_status(m)
    if not s.get("scorerQualified"):
        return {"allowed": False, "reason": "scorer evidence not qualified", "dailyCap": 0}
    if not s.get("simulatorQualified"):
        return {"allowed": False, "reason": "dry-run pilot not qualified", "dailyCap": 0}
    if s.get("guardianSuspended"):
        return {"allowed": False, "reason": "guardian suspended AI exits", "dailyCap": 0}
    if s.get("guardianPendingReview"):
        return {"allowed": False, "reason": "guardian review hold active", "dailyCap": 0}
    return {
        "allowed": True,
        "reason": f"promotion state {s.get('state')}",
        "dailyCap": max(1, _i(s.get("dailyAiExitCap"), 1)),
    }


def _worker(m) -> None:
    print(
        f"{VERSION} AUTONOMOUS AI EXIT PROMOTION | "
        "shadow->simulation->pilot->trusted->graduated hard_safety=UNCHANGED",
        flush=True,
    )
    while True:
        try:
            promotion_status(m)
        except Exception as exc:
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
            print(f"{VERSION} PROMOTION ERROR | {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


def install_v18366_autonomous_ai_exit_promotion(app, m) -> None:
    global _started
    m.v18366_ai_exit_promotion_status = lambda: promotion_status(m)
    m.v18366_ai_exit_live_preflight = lambda: live_preflight(m)

    @app.get("/v18/ai-exit-promotion")
    def api_v18366(request: m.Request):
        m.verify_api_key(request)
        payload = promotion_status(m)
        payload["liveAuthority"] = False
        payload["note"] = (
            "Promotion readiness only. V18.3.63 still requires its explicit pilot enable switch. "
            "Guardian and hard safety remain authoritative."
        )
        return {"ok": True, **payload}

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v18366-ai-exit-promotion").start()
