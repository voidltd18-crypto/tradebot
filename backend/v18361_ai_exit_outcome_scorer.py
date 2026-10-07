"""V18.3.61 — AI Exit Outcome Scorer.

Scores V18.3.60 shadow HOLD / PROTECT / EXIT decisions against what the stock
actually does afterwards. Research-only: no order submission and no live sell
authority.

The scorer advances only while Alpaca reports the US market open. That keeps
5/15/30/60 minute horizons tied to trading time rather than overnight wall time.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional
from fastapi import Request

VERSION = "V18.3.61"
POLL_SECONDS = 10
ANCHOR_SPACING_SECONDS = 300
HORIZONS_MIN = (5, 15, 30, 60)
NEUTRAL_BAND_PCT = 0.05
_runtime: Dict[str, Any] = {
    "version": VERSION,
    "mode": "SHADOW_SCORING",
    "liveAuthority": False,
    "startedAt": None,
    "lastRunAt": None,
    "lastError": None,
    "cycles": 0,
    "marketOpen": False,
    "anchors": 0,
    "outcomes": 0,
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


def _dt(v: Any) -> Optional[datetime]:
    try:
        raw = str(v or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        out = datetime.fromisoformat(raw)
        if out.tzinfo is None:
            out = out.replace(tzinfo=UTC)
        return out.astimezone(UTC)
    except Exception:
        return None


def _columns(conn, table: str) -> set[str]:
    try:
        return {str(r["name"]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _ensure_tables(m) -> None:
    conn = m.db_connect()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS v18361_exit_outcome_anchors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL UNIQUE,
            observed_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            decision_confidence_pct REAL,
            decision_price REAL NOT NULL,
            pnl_pct REAL,
            peak_pct REAL,
            giveback_pct REAL,
            momentum REAL,
            held_minutes INTEGER,
            market_regime TEXT,
            market_value_gbp REAL,
            open_seconds_elapsed REAL NOT NULL DEFAULT 0,
            last_tick_at TEXT,
            created_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS v18361_exit_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anchor_id INTEGER NOT NULL,
            horizon_min INTEGER NOT NULL,
            scored_at TEXT NOT NULL,
            future_price REAL NOT NULL,
            future_return_pct REAL NOT NULL,
            decision_edge_pct REAL NOT NULL,
            simulated_edge_gbp REAL,
            verdict TEXT NOT NULL,
            UNIQUE(anchor_id, horizon_min)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v18361_anchor_symbol ON v18361_exit_outcome_anchors(symbol, observed_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_v18361_outcome_horizon ON v18361_exit_outcomes(horizon_min, verdict)")
        conn.execute("""CREATE TABLE IF NOT EXISTS v18361_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""")
        conn.execute("INSERT OR IGNORE INTO v18361_meta(key,value) VALUES ('lastDecisionId','0')")
        conn.commit()
    finally:
        conn.close()


def _market_open(m) -> bool:
    try:
        return bool(getattr(m.trading_client.get_clock(), "is_open", False))
    except Exception:
        try:
            payload = m.get_effective_market_status_payload()
            return bool(payload.get("isOpen"))
        except Exception:
            return False


def _decision_market_value_gbp(row: Dict[str, Any]) -> float:
    try:
        features = json.loads(str(row.get("features_json") or "{}"))
        return max(0.0, _f(features.get("marketValueGbp")))
    except Exception:
        return 0.0


def _accept_new_anchors(m, is_open: bool) -> int:
    # Only sample new decisions while the market is actually open.
    if not is_open:
        return 0
    conn = m.db_connect()
    accepted = 0
    try:
        if "v18360_ai_exit_decisions" not in {
            str(r["name"]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }:
            return 0
        cursor_row = conn.execute(
            "SELECT value FROM v18361_meta WHERE key='lastDecisionId'"
        ).fetchone()
        last_id = _i(cursor_row["value"] if cursor_row else 0)
        rows = conn.execute(
            """SELECT id,observed_at,symbol,action,confidence_pct,price,pnl_pct,peak_pct,
                      giveback_pct,momentum,held_minutes,market_regime,features_json
               FROM v18360_ai_exit_decisions
               WHERE id>? ORDER BY id ASC LIMIT 500""",
            (last_id,),
        ).fetchall()
        for raw in rows:
            row = dict(raw)
            symbol = str(row.get("symbol") or "").upper()
            action = str(row.get("action") or "").upper()
            price = _f(row.get("price"))
            if not symbol or action not in ("HOLD", "PROTECT", "EXIT") or price <= 0:
                continue

            prev = conn.execute(
                """SELECT observed_at,action FROM v18361_exit_outcome_anchors
                   WHERE symbol=? ORDER BY id DESC LIMIT 1""",
                (symbol,),
            ).fetchone()
            should_accept = True
            if prev:
                prev_dt = _dt(prev["observed_at"])
                cur_dt = _dt(row.get("observed_at"))
                seconds = (cur_dt - prev_dt).total_seconds() if prev_dt and cur_dt else 0.0
                if str(prev["action"] or "").upper() == action and seconds < ANCHOR_SPACING_SECONDS:
                    should_accept = False
            if not should_accept:
                continue

            conn.execute(
                """INSERT OR IGNORE INTO v18361_exit_outcome_anchors
                   (decision_id,observed_at,symbol,action,decision_confidence_pct,decision_price,
                    pnl_pct,peak_pct,giveback_pct,momentum,held_minutes,market_regime,
                    market_value_gbp,open_seconds_elapsed,last_tick_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)""",
                (
                    _i(row.get("id")), str(row.get("observed_at") or _now()), symbol, action,
                    _f(row.get("confidence_pct")), price, _f(row.get("pnl_pct")),
                    _f(row.get("peak_pct")), _f(row.get("giveback_pct")), _f(row.get("momentum")),
                    _i(row.get("held_minutes")), str(row.get("market_regime") or "UNKNOWN"),
                    _decision_market_value_gbp(row), _now(), _now(),
                ),
            )
            accepted += 1
            conn.execute(
                "UPDATE v18361_meta SET value=? WHERE key='lastDecisionId'",
                (str(_i(row.get("id"))),),
            )
        if rows:
            # Advance the cursor even when a decision was intentionally skipped by
            # the 5-minute anchor spacing rule, otherwise the scorer would reread
            # the same skipped rows forever.
            conn.execute(
                "UPDATE v18361_meta SET value=? WHERE key='lastDecisionId'",
                (str(_i(dict(rows[-1]).get("id"))),),
            )
        conn.commit()
        return accepted
    finally:
        conn.close()


def _advance_open_time(m, is_open: bool) -> None:
    conn = m.db_connect()
    try:
        rows = conn.execute(
            """SELECT id,last_tick_at,open_seconds_elapsed FROM v18361_exit_outcome_anchors
               WHERE open_seconds_elapsed < ?""",
            (max(HORIZONS_MIN) * 60,),
        ).fetchall()
        now = datetime.now(UTC)
        for r in rows:
            last = _dt(r["last_tick_at"]) or now
            delta = max(0.0, min(60.0, (now - last).total_seconds()))
            elapsed = _f(r["open_seconds_elapsed"])
            if is_open:
                elapsed += delta
            conn.execute(
                "UPDATE v18361_exit_outcome_anchors SET open_seconds_elapsed=?, last_tick_at=? WHERE id=?",
                (elapsed, now.isoformat(), _i(r["id"])),
            )
        conn.commit()
    finally:
        conn.close()


def _quote_price(m, symbol: str) -> float:
    try:
        q = m.get_quote(symbol)
        return _f(q.get("mid") or q.get("last") or q.get("price"))
    except Exception:
        return 0.0


def _score_due(m, is_open: bool) -> int:
    if not is_open:
        return 0
    conn = m.db_connect()
    scored = 0
    try:
        anchors = conn.execute(
            """SELECT * FROM v18361_exit_outcome_anchors
               WHERE open_seconds_elapsed >= ? ORDER BY id ASC LIMIT 500""",
            (min(HORIZONS_MIN) * 60,),
        ).fetchall()
        for raw in anchors:
            a = dict(raw)
            anchor_id = _i(a.get("id"))
            elapsed = _f(a.get("open_seconds_elapsed"))
            existing = {
                _i(r["horizon_min"])
                for r in conn.execute(
                    "SELECT horizon_min FROM v18361_exit_outcomes WHERE anchor_id=?",
                    (anchor_id,),
                ).fetchall()
            }
            due = [h for h in HORIZONS_MIN if h not in existing and elapsed >= h * 60]
            if not due:
                continue
            future = _quote_price(m, str(a.get("symbol") or ""))
            base = _f(a.get("decision_price"))
            if future <= 0 or base <= 0:
                continue
            future_return = ((future / base) - 1.0) * 100.0
            action = str(a.get("action") or "").upper()
            # HOLD benefits when price rises; EXIT/PROTECT benefit when subsequent
            # price falls. This is counterfactual decision edge, not realised P&L.
            edge = future_return if action == "HOLD" else -future_return
            verdict = "GOOD" if edge > NEUTRAL_BAND_PCT else ("BAD" if edge < -NEUTRAL_BAND_PCT else "NEUTRAL")
            market_value_gbp = _f(a.get("market_value_gbp"))
            edge_gbp = market_value_gbp * edge / 100.0 if market_value_gbp > 0 else None
            for h in due:
                conn.execute(
                    """INSERT OR IGNORE INTO v18361_exit_outcomes
                       (anchor_id,horizon_min,scored_at,future_price,future_return_pct,
                        decision_edge_pct,simulated_edge_gbp,verdict)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (anchor_id, h, _now(), future, future_return, edge, edge_gbp, verdict),
                )
                scored += 1
        conn.commit()
        return scored
    finally:
        conn.close()


def _stats(m) -> Dict[str, Any]:
    conn = m.db_connect()
    try:
        total_anchors = _i(conn.execute("SELECT COUNT(*) c FROM v18361_exit_outcome_anchors").fetchone()["c"])
        total_outcomes = _i(conn.execute("SELECT COUNT(*) c FROM v18361_exit_outcomes").fetchone()["c"])
        by_horizon = []
        for h in HORIZONS_MIN:
            r = conn.execute(
                """SELECT COUNT(*) n,
                          SUM(CASE WHEN verdict='GOOD' THEN 1 ELSE 0 END) good,
                          SUM(CASE WHEN verdict='BAD' THEN 1 ELSE 0 END) bad,
                          SUM(CASE WHEN verdict='NEUTRAL' THEN 1 ELSE 0 END) neutral,
                          AVG(decision_edge_pct) avg_edge,
                          SUM(COALESCE(simulated_edge_gbp,0)) edge_gbp
                   FROM v18361_exit_outcomes WHERE horizon_min=?""",
                (h,),
            ).fetchone()
            n = _i(r["n"])
            good = _i(r["good"])
            bad = _i(r["bad"])
            denom = good + bad
            by_horizon.append({
                "horizonMin": h,
                "samples": n,
                "good": good,
                "bad": bad,
                "neutral": _i(r["neutral"]),
                "decisionAccuracyPct": round((good / denom) * 100.0, 1) if denom else 0.0,
                "avgDecisionEdgePct": round(_f(r["avg_edge"]), 4),
                "simulatedEdgeGbp": round(_f(r["edge_gbp"]), 2),
            })

        by_action = []
        for action in ("HOLD", "PROTECT", "EXIT"):
            r = conn.execute(
                """SELECT COUNT(*) n,
                          SUM(CASE WHEN o.verdict='GOOD' THEN 1 ELSE 0 END) good,
                          SUM(CASE WHEN o.verdict='BAD' THEN 1 ELSE 0 END) bad,
                          AVG(o.decision_edge_pct) edge
                   FROM v18361_exit_outcomes o
                   JOIN v18361_exit_outcome_anchors a ON a.id=o.anchor_id
                   WHERE o.horizon_min=30 AND a.action=?""",
                (action,),
            ).fetchone()
            n = _i(r["n"])
            good = _i(r["good"])
            bad = _i(r["bad"])
            by_action.append({
                "action": action,
                "samples30m": n,
                "good": good,
                "bad": bad,
                "accuracyPct": round((good / (good + bad)) * 100.0, 1) if good + bad else 0.0,
                "avgEdgePct": round(_f(r["edge"]), 4),
            })

        h30 = next((x for x in by_horizon if x["horizonMin"] == 30), {})
        exit30 = next((x for x in by_action if x["action"] == "EXIT"), {})
        pilot_eligible = bool(
            _i(h30.get("samples")) >= 50
            and _f(h30.get("decisionAccuracyPct")) >= 55.0
            and _f(h30.get("avgDecisionEdgePct")) > 0.10
            and _i(exit30.get("samples30m")) >= 10
            and _f(exit30.get("avgEdgePct")) > 0.0
        )
        return {
            "anchors": total_anchors,
            "outcomes": total_outcomes,
            "byHorizon": by_horizon,
            "byAction30m": by_action,
            "pilotEligible": pilot_eligible,
            "pilotGate": {
                "required30mSamples": 50,
                "required30mAccuracyPct": 55.0,
                "required30mAvgEdgePct": 0.10,
                "requiredExit30mSamples": 10,
                "requiresPositiveExitEdge": True,
            },
        }
    finally:
        conn.close()


def _worker(m) -> None:
    print(f"{VERSION} AI EXIT OUTCOME SCORER | shadow_only=True live_authority=False horizons=5/15/30/60m", flush=True)
    while True:
        try:
            is_open = _market_open(m)
            _accept_new_anchors(m, is_open)
            _advance_open_time(m, is_open)
            _score_due(m, is_open)
            stats = _stats(m)
            with _lock:
                _runtime.update({
                    "lastRunAt": _now(),
                    "lastError": None,
                    "cycles": _i(_runtime.get("cycles")) + 1,
                    "marketOpen": bool(is_open),
                    "anchors": stats["anchors"],
                    "outcomes": stats["outcomes"],
                })
        except Exception as exc:
            with _lock:
                _runtime["lastRunAt"] = _now()
                _runtime["lastError"] = f"{type(exc).__name__}: {exc}"
            print(f"{VERSION} OUTCOME SCORER ERROR | {type(exc).__name__}: {exc}", flush=True)
        time.sleep(POLL_SECONDS)


def install_v18361_ai_exit_outcome_scorer(app, m) -> None:
    global _started
    _ensure_tables(m)

    def _pilot_eligible():
        try:
            return bool(_stats(m).get("pilotEligible"))
        except Exception:
            return False

    m.v18361_exit_pilot_eligible = _pilot_eligible
    if not _runtime.get("startedAt"):
        _runtime["startedAt"] = _now()

    @app.get("/v18/ai-exit-outcomes")
    def api_v18361_ai_exit_outcomes(request: Request):
        m.verify_api_key(request)
        stats = _stats(m)
        with _lock:
            runtime = dict(_runtime)
        return {
            "ok": True,
            **runtime,
            **stats,
            "liveAuthority": False,
            "note": "Research only. Pilot eligibility does not enable selling automatically.",
        }

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v18361-exit-outcome-scorer").start()
