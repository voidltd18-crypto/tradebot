"""V18.3.57 Capital Earnback Ladder.

Stock-only capital permission ladder.

The bot starts with an £85 stock exposure ceiling. It must earn higher ceilings
with fresh profitable closed stock trades:
- 5 consecutive green closes -> +£15 allowance.
- 2 losses in the last 3 closes -> -£15 allowance.
- A negative rolling 5-trade P&L -> -£15 allowance.
- A loss resets the promotion streak.
- The allowance never falls below £85.

Important: this does NOT release or edit Piggy Bank money. The ladder only limits
how much stock exposure the bot is permitted to carry. If extra unprotected cash
does not actually exist outside the Piggy Bank, the existing banking/cash rules
still win and no protected money is touched.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

STATE_PATH = os.environ.get("V18357_STATE_PATH", "/var/data/v18357_capital_ladder.json")
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
            value = json.load(fh)
            return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _save(state: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


def _pnl_gbp(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("pnl_gbp") or 0.0)
    except Exception:
        return 0.0


def install_v18357_capital_earnback_ladder(app, m) -> None:
    state = _load()

    if not state:
        conn = m.db_connect()
        try:
            row = conn.execute(
                """SELECT COALESCE(MAX(id),0) AS id
                   FROM closed_trades
                   WHERE symbol NOT LIKE '%/%'"""
            ).fetchone()
            start_id = int(row["id"] if row else 0)
        finally:
            conn.close()

        state = {
            "version": "V18.3.57",
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

    # Repair/upgrade any earlier draft state shape safely.
    state.setdefault("rung", 0)
    state["currentCapGbp"] = BASE_CAP_GBP + (int(state.get("rung") or 0) * STEP_GBP)
    state.setdefault("winStreak", 0)
    state.setdefault("recent", [])
    state.setdefault("promotions", 0)
    state.setdefault("rollbacks", 0)
    state.setdefault("enabled", True)
    state.pop("pendingCapitalChangeGbp", None)
    state.pop("window", None)
    _save(state)

    def fresh_stock_trades(after_id: int) -> List[Dict[str, Any]]:
        conn = m.db_connect()
        try:
            qty_eps = float(getattr(m, "PHANTOM_CLOSED_TRADE_QTY_EPSILON", 0.000001) or 0.000001)
            min_notional = float(getattr(m, "PHANTOM_CLOSED_TRADE_MIN_NOTIONAL_USD", 0.50) or 0.50)
            rows = conn.execute(
                """SELECT * FROM closed_trades
                   WHERE id>?
                     AND COALESCE(qty,0)>?
                     AND ABS(COALESCE(qty,0)*COALESCE(exit_price,0))>=?
                     AND symbol NOT LIKE '%/%'
                   ORDER BY id ASC""",
                (after_id, qty_eps, min_notional),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def evaluate_trade(t: Dict[str, Any]) -> None:
        nonlocal state
        pnl = _pnl_gbp(t)
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

        action = "HOLD"
        reason = "collecting fresh stock evidence"
        rung = int(state.get("rung") or 0)

        last3 = recent[-ROLLBACK_WINDOW:]
        losses_last3 = sum(1 for x in last3 if x.get("outcome") == "LOSS")
        last5 = recent[-5:]
        rolling5 = sum(float(x.get("pnlGbp") or 0.0) for x in last5)

        should_rollback = False
        if rung > 0 and len(last3) >= ROLLBACK_WINDOW and losses_last3 >= ROLLBACK_LOSSES:
            should_rollback = True
            reason = f"{losses_last3} losses in last {ROLLBACK_WINDOW}"
        elif rung > 0 and len(last5) >= 5 and rolling5 < 0:
            should_rollback = True
            reason = f"rolling 5-trade P&L £{rolling5:.2f}"

        if should_rollback:
            rung = max(0, rung - 1)
            state["rung"] = rung
            state["currentCapGbp"] = BASE_CAP_GBP + (rung * STEP_GBP)
            state["rollbacks"] = int(state.get("rollbacks") or 0) + 1
            state["winStreak"] = 0
            action = "ROLLBACK"
        elif int(state.get("winStreak") or 0) >= WINS_TO_PROMOTE:
            rung += 1
            state["rung"] = rung
            state["currentCapGbp"] = BASE_CAP_GBP + (rung * STEP_GBP)
            state["promotions"] = int(state.get("promotions") or 0) + 1
            state["winStreak"] = 0
            action = "PROMOTE"
            reason = f"{WINS_TO_PROMOTE} consecutive green closes"

        state["lastProcessedTradeId"] = int(t.get("id") or 0)
        state["updatedAt"] = _now()
        _save(state)

        after = float(state.get("currentCapGbp") or BASE_CAP_GBP)
        _RUNTIME["lastAction"] = action
        _RUNTIME["lastEvaluation"] = {
            "tradeId": int(t.get("id") or 0),
            "symbol": str(t.get("symbol") or "").upper(),
            "pnlGbp": round(pnl, 2),
            "outcome": outcome,
            "action": action,
            "reason": reason,
            "capBeforeGbp": round(before, 2),
            "capAfterGbp": round(after, 2),
            "winStreak": int(state.get("winStreak") or 0),
            "at": _now(),
        }

        if action in ("PROMOTE", "ROLLBACK"):
            print(
                f"V18.3.57 CAPITAL EARNBACK | {action} | "
                f"symbol={t.get('symbol')} pnl=£{pnl:.2f} "
                f"cap=£{before:.2f}->£{after:.2f} reason={reason}",
                flush=True,
            )

    def evaluate_once() -> None:
        nonlocal state
        if not state.get("enabled", True):
            return
        for t in fresh_stock_trades(int(state.get("lastProcessedTradeId") or 0)):
            evaluate_trade(t)

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
                symbol = str(p.get("symbol") or "").upper()
                if "/" in symbol:
                    continue
                mv = p.get("marketValue")
                if mv is None:
                    mv = p.get("market_value")
                if mv is None:
                    qty = abs(float(p.get("qty") or 0.0))
                    price = float(p.get("price") or p.get("current_price") or 0.0)
                    mv = qty * price
                total_usd += abs(float(mv or 0.0))
            except Exception:
                continue

        try:
            fx = float(m.get_usd_to_gbp_rate())
        except Exception:
            fx = 0.78
        return max(0.0, total_usd * max(0.01, fx))

    # Central stock sizing hook. Existing banking/cash sizing still runs first;
    # this wrapper can only REDUCE the order, never increase it.
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

            headroom_usd = headroom_gbp / max(0.01, fx)
            allowed_usd = max(0.0, min(base_usd, headroom_usd))

            if allowed_usd + 0.01 < base_usd:
                print(
                    f"V18.3.57 CAPITAL CAP | base_usd={base_usd:.2f} "
                    f"allowed_usd={allowed_usd:.2f} cap_gbp={cap_gbp:.2f} "
                    f"stock_exposure_gbp={exposure_gbp:.2f}",
                    flush=True,
                )
            return allowed_usd

        m.calculate_new_position_notional = ladder_notional
        _RUNTIME["sizingHookInstalled"] = True
    else:
        print("V18.3.57 CAPITAL EARNBACK | sizing hook missing; evidence-only", flush=True)

    def loop() -> None:
        _RUNTIME["workerStarted"] = True
        while True:
            try:
                with _LOCK:
                    evaluate_once()
                _RUNTIME["lastError"] = None
            except Exception as exc:
                _RUNTIME["lastError"] = str(exc)
                print(f"V18.3.57 CAPITAL EARNBACK ERROR | {exc}", flush=True)
            time.sleep(POLL_SECONDS)

    threading.Thread(target=loop, name="v18357-capital-ladder", daemon=True).start()

    @app.get("/v18/capital-earnback-ladder")
    def capital_earnback_ladder():
        with _LOCK:
            try:
                evaluate_once()
            except Exception:
                pass

            recent = list(state.get("recent") or [])
            last3 = recent[-3:]
            last5 = recent[-5:]
            cap = float(state.get("currentCapGbp") or BASE_CAP_GBP)
            exposure = stock_exposure_gbp()

            return {
                "ok": True,
                "version": "V18.3.57",
                "enabled": bool(state.get("enabled", True)),
                "mode": "EARNED_CAPITAL_ONLY",
                "stockOnly": True,
                "cryptoChanged": False,
                "piggyBankChanged": False,
                "rules": {
                    "baseCapGbp": BASE_CAP_GBP,
                    "stepGbp": STEP_GBP,
                    "winsToPromote": WINS_TO_PROMOTE,
                    "promotionRule": "5 consecutive fresh profitable stock closes",
                    "rollbackLosses": ROLLBACK_LOSSES,
                    "rollbackWindow": ROLLBACK_WINDOW,
                    "rollingFiveNegativeRollback": True,
                },
                "state": {
                    "startedAt": state.get("startedAt"),
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
                "note": "The ladder only reduces stock buying permission. Piggy Bank money is never released automatically.",
            }

    _RUNTIME["installed"] = True
    print(
        "V18.3.57 CAPITAL EARNBACK LADDER | "
        f"base=£{BASE_CAP_GBP:.2f} step=£{STEP_GBP:.2f} "
        f"cap=£{float(state.get('currentCapGbp') or BASE_CAP_GBP):.2f} "
        f"wins={int(state.get('winStreak') or 0)}/{WINS_TO_PROMOTE} "
        f"sizing_hook={bool(_RUNTIME['sizingHookInstalled'])} "
        "piggy_changed=False crypto_changed=False",
        flush=True,
    )
