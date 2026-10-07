"""V18.3.58 Earned Capital Enforcement.

Stock-only capital permission ladder.

Rules:
- Start stock exposure cap: £85.
- 5 consecutive fresh profitable stock closes -> +£15 cap.
- 2 losses in the last 3 closes -> -£15 cap.
- Negative rolling 5-trade P&L -> -£15 cap.
- Any non-winning close resets the promotion streak.
- Cap never falls below £85.

This module NEVER releases or edits Piggy Bank money. It only reduces the
stock bot's normal sizing permission. Existing banking/cash rules still run
first, so protected funds stay protected.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

STATE_PATH = os.environ.get("V18358_STATE_PATH", "/var/data/v18358_capital_ladder.json")
BASE_CAP_GBP = 85.0
STEP_GBP = 15.0
WINS_TO_PROMOTE = 5
ROLLBACK_WINDOW = 3
ROLLBACK_LOSSES = 2
POLL_SECONDS = 15

_LOCK = threading.RLock()
_RUNTIME: Dict[str, Any] = {
    "installed": False,
    "sizingHookInstalled": False,
    "workerStarted": False,
    "lastError": None,
    "lastEvaluation": None,
    "lastAction": "BASELINE",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> Dict[str, Any]:
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as fh:
            v = json.load(fh)
            return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _save(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def install_v18357_capital_earnback_ladder(app, m) -> None:
    state = _load()
    if not state:
        conn = m.db_connect()
        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(id),0) AS id FROM closed_trades WHERE symbol NOT LIKE '%/%'"
            ).fetchone()
            start_id = int(row["id"] if row else 0)
        finally:
            conn.close()
        state = {
            "version": "V18.3.58",
            "startedAt": _now(),
            "startTradeId": start_id,
            "lastProcessedTradeId": start_id,
            "rung": 0,
            "currentCapGbp": BASE_CAP_GBP,
            "winStreak": 0,
            "recent": [],
            "promotions": 0,
            "rollbacks": 0,
            "enabled": True,
        }
        _save(state)

    def fresh_trades(after_id: int) -> List[Dict[str, Any]]:
        conn = m.db_connect()
        try:
            qty_eps = float(getattr(m, "PHANTOM_CLOSED_TRADE_QTY_EPSILON", 0.000001) or 0.000001)
            min_notional = float(getattr(m, "PHANTOM_CLOSED_TRADE_MIN_NOTIONAL_USD", 0.50) or 0.50)
            rows = conn.execute(
                """SELECT * FROM closed_trades
                   WHERE id>? AND symbol NOT LIKE '%/%'
                     AND COALESCE(qty,0)>?
                     AND ABS(COALESCE(qty,0)*COALESCE(exit_price,0))>=?
                   ORDER BY id ASC""",
                (after_id, qty_eps, min_notional),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def process_trade(t: Dict[str, Any]) -> None:
        nonlocal state
        pnl = float(t.get("pnl_gbp") or 0.0)
        outcome = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "FLAT")
        before = float(state.get("currentCapGbp") or BASE_CAP_GBP)

        recent = list(state.get("recent") or [])
        recent.append({
            "id": int(t.get("id") or 0),
            "symbol": str(t.get("symbol") or "").upper(),
            "pnlGbp": round(pnl, 4),
            "outcome": outcome,
            "timestamp": t.get("timestamp"),
        })
        recent = recent[-10:]
        state["recent"] = recent

        if outcome == "WIN":
            state["winStreak"] = int(state.get("winStreak") or 0) + 1
        else:
            state["winStreak"] = 0

        rung = int(state.get("rung") or 0)
        action = "HOLD"
        reason = "collecting fresh stock evidence"

        last3 = recent[-ROLLBACK_WINDOW:]
        last5 = recent[-5:]
        losses_last3 = sum(1 for x in last3 if x.get("outcome") == "LOSS")
        rolling5 = sum(float(x.get("pnlGbp") or 0.0) for x in last5)

        rollback = (
            rung > 0
            and (
                (len(last3) >= 3 and losses_last3 >= ROLLBACK_LOSSES)
                or (len(last5) >= 5 and rolling5 < 0)
            )
        )

        if rollback:
            rung = max(0, rung - 1)
            state["rung"] = rung
            state["currentCapGbp"] = BASE_CAP_GBP + rung * STEP_GBP
            state["rollbacks"] = int(state.get("rollbacks") or 0) + 1
            state["winStreak"] = 0
            action = "ROLLBACK"
            reason = (
                f"{losses_last3} losses in last 3"
                if losses_last3 >= ROLLBACK_LOSSES
                else f"rolling 5-trade P&L £{rolling5:.2f}"
            )
        elif int(state.get("winStreak") or 0) >= WINS_TO_PROMOTE:
            rung += 1
            state["rung"] = rung
            state["currentCapGbp"] = BASE_CAP_GBP + rung * STEP_GBP
            state["promotions"] = int(state.get("promotions") or 0) + 1
            state["winStreak"] = 0
            action = "PROMOTE"
            reason = "5 consecutive green closes"

        state["lastProcessedTradeId"] = int(t.get("id") or 0)
        state["updatedAt"] = _now()
        _save(state)

        _RUNTIME["lastAction"] = action
        _RUNTIME["lastEvaluation"] = {
            "tradeId": int(t.get("id") or 0),
            "symbol": str(t.get("symbol") or "").upper(),
            "pnlGbp": round(pnl, 2),
            "outcome": outcome,
            "action": action,
            "reason": reason,
            "capBeforeGbp": round(before, 2),
            "capAfterGbp": round(float(state.get("currentCapGbp") or BASE_CAP_GBP), 2),
            "at": _now(),
        }

        if action in ("PROMOTE", "ROLLBACK"):
            print(
                f"V18.3.58 EARNED CAPITAL | {action} | symbol={t.get('symbol')} "
                f"pnl=£{pnl:.2f} cap=£{before:.2f}->£{float(state.get('currentCapGbp') or BASE_CAP_GBP):.2f} "
                f"reason={reason}",
                flush=True,
            )

    def evaluate_once() -> None:
        if not state.get("enabled", True):
            return
        for t in fresh_trades(int(state.get("lastProcessedTradeId") or 0)):
            process_trade(t)

    def stock_exposure_gbp() -> float:
        try:
            positions = m.get_all_positions()
        except Exception:
            return 0.0
        total_usd = 0.0
        for p in positions or []:
            try:
                if not isinstance(p, dict):
                    continue
                sym = str(p.get("symbol") or "").upper()
                if "/" in sym:
                    continue
                mv = p.get("marketValue")
                if mv is None:
                    mv = p.get("market_value")
                if mv is None:
                    mv = abs(float(p.get("qty") or 0) * float(p.get("price") or p.get("current_price") or 0))
                total_usd += abs(float(mv or 0))
            except Exception:
                continue
        try:
            fx = float(m.get_usd_to_gbp_rate())
        except Exception:
            fx = 0.78
        return max(0.0, total_usd * max(0.01, fx))

    original_notional = getattr(m, "calculate_new_position_notional", None)
    if callable(original_notional):
        def ladder_notional():
            base_usd = max(0.0, float(original_notional() or 0.0))
            if base_usd <= 0:
                return base_usd
            cap_gbp = float(state.get("currentCapGbp") or BASE_CAP_GBP)
            exposure_gbp = stock_exposure_gbp()
            headroom_gbp = max(0.0, cap_gbp - exposure_gbp)
            try:
                fx = float(m.get_usd_to_gbp_rate())
            except Exception:
                fx = 0.78
            allowed_usd = min(base_usd, headroom_gbp / max(0.01, fx))
            return max(0.0, allowed_usd)

        m.calculate_new_position_notional = ladder_notional
        _RUNTIME["sizingHookInstalled"] = True
    else:
        print("V18.3.58 EARNED CAPITAL | sizing hook missing; evidence-only", flush=True)

    def worker():
        _RUNTIME["workerStarted"] = True
        while True:
            try:
                with _LOCK:
                    evaluate_once()
                _RUNTIME["lastError"] = None
            except Exception as exc:
                _RUNTIME["lastError"] = str(exc)
                print(f"V18.3.58 EARNED CAPITAL ERROR | {exc}", flush=True)
            time.sleep(POLL_SECONDS)

    threading.Thread(target=worker, name="v18358-earned-capital", daemon=True).start()

    @app.get("/v18/capital-earnback-ladder")
    def capital_earnback_ladder():
        with _LOCK:
            evaluate_once()
            recent = list(state.get("recent") or [])
            last3 = recent[-3:]
            last5 = recent[-5:]
            cap = float(state.get("currentCapGbp") or BASE_CAP_GBP)
            exposure = stock_exposure_gbp()
            return {
                "ok": True,
                "version": "V18.3.58",
                "enabled": bool(state.get("enabled", True)),
                "mode": "EARNED_CAPITAL_ONLY",
                "automaticMoneyMovement": False,
                "stockOnly": True,
                "cryptoChanged": False,
                "piggyBankChanged": False,
                "rules": {
                    "baseCapGbp": BASE_CAP_GBP,
                    "stepGbp": STEP_GBP,
                    "winsToPromote": WINS_TO_PROMOTE,
                    "promotionRule": "5 consecutive fresh profitable stock closes",
                    "rollback": "2 losses in last 3 OR negative rolling 5-trade P&L",
                },
                "state": {
                    "rung": int(state.get("rung") or 0),
                    "currentCapGbp": round(cap, 2),
                    "winStreak": int(state.get("winStreak") or 0),
                    "winsRemaining": max(0, WINS_TO_PROMOTE - int(state.get("winStreak") or 0)),
                    "promotions": int(state.get("promotions") or 0),
                    "rollbacks": int(state.get("rollbacks") or 0),
                    "stockExposureGbp": round(exposure, 2),
                    "headroomGbp": round(max(0.0, cap - exposure), 2),
                    "lastThreeLosses": sum(1 for x in last3 if x.get("outcome") == "LOSS"),
                    "rollingFivePnlGbp": round(sum(float(x.get("pnlGbp") or 0.0) for x in last5), 2),
                    "recent": recent,
                },
                "runtime": dict(_RUNTIME),
                "note": "Allowance can only reduce normal stock sizing. Piggy Bank funds are never released automatically.",
            }

    _RUNTIME["installed"] = True
    print(
        f"V18.3.58 EARNED CAPITAL ENFORCEMENT | cap=£{float(state.get('currentCapGbp') or BASE_CAP_GBP):.2f} "
        f"wins={int(state.get('winStreak') or 0)}/{WINS_TO_PROMOTE} "
        f"sizing_hook={bool(_RUNTIME['sizingHookInstalled'])} piggy_changed=False crypto_changed=False",
        flush=True,
    )
