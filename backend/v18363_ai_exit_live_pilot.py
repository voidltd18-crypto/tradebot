"""V18.3.63 — AI Exit Live Pilot Gate.

Adds the controlled bridge from Shadow intelligence to live stock exits.
Default is SAFE/OFF. Even when explicitly enabled by environment, live AI exits
are permitted only after V18.3.61 evidence qualifies and the current decision
passes additional confidence/confirmation/cadence gates.

This module never overrides hard stops, equity protection, Piggy protection,
broker/PDT restrictions or emergency controls.
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, UTC
from typing import Any, Dict

VERSION = "V18.3.63"
PILOT_ENABLED = str(os.getenv("TRADEBOT_AI_EXIT_PILOT_ENABLED", "false")).lower() in ("1","true","yes","on")
MIN_DECISION_CONFIDENCE = max(60.0, float(os.getenv("TRADEBOT_AI_EXIT_PILOT_MIN_CONFIDENCE", "75") or 75))
REQUIRED_CONSECUTIVE_EXIT = max(2, int(os.getenv("TRADEBOT_AI_EXIT_PILOT_CONFIRMATIONS", "2") or 2))
MAX_AI_EXITS_PER_DAY = max(1, int(os.getenv("TRADEBOT_AI_EXIT_PILOT_MAX_EXITS_PER_DAY", "1") or 1))
MIN_SECONDS_BETWEEN_CONFIRMATIONS = max(5, int(os.getenv("TRADEBOT_AI_EXIT_PILOT_CONFIRMATION_SECONDS", "10") or 10))

_runtime: Dict[str, Any] = {
    "version": VERSION,
    "pilotEnabled": PILOT_ENABLED,
    "liveAuthority": False,
    "pilotEligible": False,
    "armed": False,
    "minDecisionConfidencePct": MIN_DECISION_CONFIDENCE,
    "requiredConsecutiveExit": REQUIRED_CONSECUTIVE_EXIT,
    "maxAiExitsPerDay": MAX_AI_EXITS_PER_DAY,
    "lastCheckedAt": None,
    "lastError": None,
    "today": None,
    "aiExitsToday": 0,
    "symbols": {},
}
_lock = threading.RLock()
_symbol_state: Dict[str, Dict[str, Any]] = {}


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


def _reset_day_if_needed() -> None:
    day = _today()
    with _lock:
        if _runtime.get("today") != day:
            _runtime["today"] = day
            _runtime["aiExitsToday"] = 0
            _symbol_state.clear()


def _pilot_eligibility_from_scorer(m) -> bool:
    try:
        # Reuse the scorer's own promotion criteria rather than duplicating
        # thresholds here. This keeps the live bridge subordinate to evidence.
        fn = getattr(m, "v18361_exit_pilot_eligible", None)
        if callable(fn):
            return bool(fn())
    except Exception:
        pass
    return False


def _latest_shadow_decision(m, symbol: str) -> Dict[str, Any]:
    try:
        fn = getattr(m, "v18360_latest_exit_decision", None)
        if callable(fn):
            row = fn(symbol)
            return dict(row or {})
    except Exception:
        pass
    return {}


def evaluate_live_exit(m, position: Dict[str, Any]) -> Dict[str, Any]:
    """Return whether the AI pilot may perform a live EXIT for this stock."""
    _reset_day_if_needed()
    symbol = str(position.get("symbol") or "").upper().strip()
    now_ts = time.time()

    eligible = _pilot_eligibility_from_scorer(m)
    decision = _latest_shadow_decision(m, symbol)
    action = str(decision.get("action") or "").upper()
    confidence = _f(decision.get("decisionConfidencePct"))
    observed_at = str(decision.get("observedAt") or "")
    live_authority = bool(PILOT_ENABLED and eligible)

    with _lock:
        _runtime["pilotEligible"] = bool(eligible)
        _runtime["liveAuthority"] = live_authority
        _runtime["armed"] = live_authority
        _runtime["lastCheckedAt"] = _now()

    if not PILOT_ENABLED:
        return {"sell": False, "reason": "AI exit pilot disabled", "symbol": symbol}
    if not eligible:
        return {"sell": False, "reason": "AI exit evidence has not qualified", "symbol": symbol}
    if _i(_runtime.get("aiExitsToday")) >= MAX_AI_EXITS_PER_DAY:
        return {"sell": False, "reason": "daily AI exit pilot limit reached", "symbol": symbol}
    if action != "EXIT":
        # Reset confirmation streak whenever the AI no longer wants out.
        with _lock:
            _symbol_state[symbol] = {
                "exitConfirmations": 0,
                "lastDecisionObservedAt": observed_at,
                "lastSeenTs": now_ts,
                "lastAction": action or "NONE",
            }
        return {"sell": False, "reason": f"AI says {action or 'NO DECISION'}", "symbol": symbol}
    if confidence < MIN_DECISION_CONFIDENCE:
        return {"sell": False, "reason": f"AI EXIT confidence {confidence:.1f}% below {MIN_DECISION_CONFIDENCE:.1f}%", "symbol": symbol}

    with _lock:
        st = _symbol_state.setdefault(symbol, {
            "exitConfirmations": 0,
            "lastDecisionObservedAt": None,
            "lastSeenTs": 0.0,
            "lastAction": "NONE",
        })
        is_new_decision = observed_at and observed_at != st.get("lastDecisionObservedAt")
        elapsed = now_ts - _f(st.get("lastSeenTs"))
        if is_new_decision and elapsed >= MIN_SECONDS_BETWEEN_CONFIRMATIONS:
            st["exitConfirmations"] = _i(st.get("exitConfirmations")) + 1
            st["lastDecisionObservedAt"] = observed_at
        st["lastSeenTs"] = now_ts
        st["lastAction"] = action
        _runtime["symbols"][symbol] = dict(st)
        confirmations = _i(st.get("exitConfirmations"))

    if confirmations < REQUIRED_CONSECUTIVE_EXIT:
        return {
            "sell": False,
            "reason": f"AI EXIT confirmation {confirmations}/{REQUIRED_CONSECUTIVE_EXIT}",
            "symbol": symbol,
            "confidencePct": confidence,
        }

    return {
        "sell": True,
        "reason": (
            f"qualified AI EXIT | confidence={confidence:.1f}% "
            f"confirmations={confirmations}/{REQUIRED_CONSECUTIVE_EXIT}"
        ),
        "symbol": symbol,
        "confidencePct": confidence,
        "decision": decision,
    }


def record_live_exit(symbol: str) -> None:
    _reset_day_if_needed()
    sym = str(symbol or "").upper()
    with _lock:
        _runtime["aiExitsToday"] = _i(_runtime.get("aiExitsToday")) + 1
        if sym in _symbol_state:
            _symbol_state[sym]["exitConfirmations"] = 0
        _runtime["lastCheckedAt"] = _now()


def install_v18363_ai_exit_live_pilot(app, m) -> None:
    m.v18363_ai_exit_pilot_decision = lambda position: evaluate_live_exit(m, position)
    m.v18363_record_ai_exit = record_live_exit

    @app.get("/v18/ai-exit-pilot")
    def api_v18363_ai_exit_pilot(request: m.Request):
        m.verify_api_key(request)
        _reset_day_if_needed()
        with _lock:
            payload = dict(_runtime)
            payload["symbols"] = dict(_runtime.get("symbols") or {})
        payload["note"] = (
            "Default OFF. Requires explicit env enable plus qualified V18.3.61 evidence. "
            "Hard safety remains authoritative."
        )
        return {"ok": True, **payload}
