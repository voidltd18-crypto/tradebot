"""V18.3.62 — AI Exit Learner.

Learns small, bounded regime/action biases from V18.3.61 scored Shadow outcomes.
Research-only: no live order authority and no direct broker actions.

The learner does not rewrite hard safety. It only calibrates the V18.3.60 shadow
decision scores so HOLD / PROTECT / EXIT can become evidence-driven over time.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict
from fastapi import Request

VERSION = "V18.3.62"
POLL_SECONDS = 300
MIN_SAMPLES_PER_BUCKET = 12
MAX_BIAS_POINTS = 8.0
EDGE_SCALE = 12.0

_runtime: Dict[str, Any] = {
    "version": VERSION,
    "mode": "SHADOW_LEARNING",
    "liveAuthority": False,
    "startedAt": None,
    "lastRunAt": None,
    "lastError": None,
    "cycles": 0,
    "qualifiedBuckets": 0,
    "biases": {},
}
_lock = threading.RLock()
_started = False


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _ensure_table(m) -> None:
    conn = m.db_connect()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS v18362_ai_exit_learning (
            bucket_key TEXT PRIMARY KEY,
            market_regime TEXT NOT NULL,
            action TEXT NOT NULL,
            samples INTEGER NOT NULL,
            good INTEGER NOT NULL,
            bad INTEGER NOT NULL,
            neutral INTEGER NOT NULL,
            accuracy_pct REAL NOT NULL,
            avg_edge_pct REAL NOT NULL,
            bias_points REAL NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        conn.commit()
    finally:
        conn.close()


def _bounded_bias(edge: float, accuracy: float) -> float:
    # Edge is the main signal. Accuracy adds only a small confidence modifier.
    raw = edge * EDGE_SCALE
    if accuracy >= 60:
        raw *= 1.15
    elif accuracy < 50:
        raw *= 0.65
    return max(-MAX_BIAS_POINTS, min(MAX_BIAS_POINTS, raw))


def _rebuild(m) -> Dict[str, Any]:
    conn = m.db_connect()
    try:
        tables = {
            str(r["name"]) for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "v18361_exit_outcomes" not in tables or "v18361_exit_outcome_anchors" not in tables:
            return {"qualifiedBuckets": 0, "biases": {}}

        rows = conn.execute(
            """SELECT
                   UPPER(COALESCE(a.market_regime,'UNKNOWN')) AS regime,
                   UPPER(a.action) AS action,
                   COUNT(*) AS samples,
                   SUM(CASE WHEN o.verdict='GOOD' THEN 1 ELSE 0 END) AS good,
                   SUM(CASE WHEN o.verdict='BAD' THEN 1 ELSE 0 END) AS bad,
                   SUM(CASE WHEN o.verdict='NEUTRAL' THEN 1 ELSE 0 END) AS neutral,
                   AVG(o.decision_edge_pct) AS avg_edge
               FROM v18361_exit_outcomes o
               JOIN v18361_exit_outcome_anchors a ON a.id=o.anchor_id
               WHERE o.horizon_min=30
               GROUP BY UPPER(COALESCE(a.market_regime,'UNKNOWN')), UPPER(a.action)"""
        ).fetchall()

        biases: Dict[str, Any] = {}
        qualified = 0
        for r in rows:
            regime = str(r["regime"] or "UNKNOWN")
            action = str(r["action"] or "HOLD")
            samples = _i(r["samples"])
            good = _i(r["good"])
            bad = _i(r["bad"])
            neutral = _i(r["neutral"])
            directional = good + bad
            accuracy = (good / directional * 100.0) if directional else 0.0
            edge = _f(r["avg_edge"])
            bias = _bounded_bias(edge, accuracy) if samples >= MIN_SAMPLES_PER_BUCKET else 0.0
            if samples >= MIN_SAMPLES_PER_BUCKET:
                qualified += 1

            key = f"{regime}|{action}"
            biases[key] = {
                "marketRegime": regime,
                "action": action,
                "samples": samples,
                "good": good,
                "bad": bad,
                "neutral": neutral,
                "accuracyPct": round(accuracy, 1),
                "avgEdgePct": round(edge, 4),
                "biasPoints": round(bias, 3),
                "qualified": samples >= MIN_SAMPLES_PER_BUCKET,
            }

            conn.execute(
                """INSERT INTO v18362_ai_exit_learning
                   (bucket_key,market_regime,action,samples,good,bad,neutral,
                    accuracy_pct,avg_edge_pct,bias_points,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(bucket_key) DO UPDATE SET
                     samples=excluded.samples,
                     good=excluded.good,
                     bad=excluded.bad,
                     neutral=excluded.neutral,
                     accuracy_pct=excluded.accuracy_pct,
                     avg_edge_pct=excluded.avg_edge_pct,
                     bias_points=excluded.bias_points,
                     updated_at=excluded.updated_at""",
                (key, regime, action, samples, good, bad, neutral, accuracy, edge, bias, _now()),
            )

        conn.commit()
        return {"qualifiedBuckets": qualified, "biases": biases}
    finally:
        conn.close()


def get_bias(m, market_regime: str, action: str) -> float:
    regime = str(market_regime or "UNKNOWN").upper()
    action = str(action or "").upper()
    conn = m.db_connect()
    try:
        r = conn.execute(
            """SELECT samples,bias_points FROM v18362_ai_exit_learning
               WHERE bucket_key=?""",
            (f"{regime}|{action}",),
        ).fetchone()
        if not r or _i(r["samples"]) < MIN_SAMPLES_PER_BUCKET:
            return 0.0
        return max(-MAX_BIAS_POINTS, min(MAX_BIAS_POINTS, _f(r["bias_points"])))
    finally:
        conn.close()


def _worker(m) -> None:
    print(
        f"{VERSION} AI EXIT LEARNER | shadow_only=True live_authority=False "
        f"min_bucket_samples={MIN_SAMPLES_PER_BUCKET} max_bias=±{MAX_BIAS_POINTS:.1f}",
        flush=True,
    )
    while True:
        try:
            result = _rebuild(m)
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = None
                _runtime["cycles"] = _i(_runtime.get("cycles")) + 1
                _runtime["qualifiedBuckets"] = _i(result.get("qualifiedBuckets"))
                _runtime["biases"] = dict(result.get("biases") or {})
        except Exception as exc:
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
            print(f"{VERSION} AI EXIT LEARNER ERROR | {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


def install_v18362_ai_exit_learner(app, m) -> None:
    global _started
    _ensure_table(m)
    if not _runtime.get("startedAt"):
        _runtime["startedAt"] = _now()

    # Expose the bounded calibration function to the V18.3.60 shadow manager.
    m.v18362_exit_learning_bias = lambda regime, action: get_bias(m, regime, action)

    @app.get("/v18/ai-exit-learning")
    def api_v18362_ai_exit_learning(request: Request):
        m.verify_api_key(request)
        with _lock:
            payload = dict(_runtime)
            payload["biases"] = list((_runtime.get("biases") or {}).values())
        payload["liveAuthority"] = False
        payload["note"] = (
            "Shadow-only bounded calibration. Hard safety and broker controls are unchanged."
        )
        return {"ok": True, **payload}

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v18362-exit-learner").start()
