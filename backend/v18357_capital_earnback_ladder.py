"""V18.3.57 Capital Earnback Ladder.

Tracks fresh closed stock trades and recommends a £15 capital release after
a strong five-trade window, with one-rung rollback after deterioration.

V18.3.57 is deliberately recommendation-only: it does not move Piggy Bank
money automatically. This keeps protected funds protected until the existing
banking layer exposes a safe partial-release primitive.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

STATE_PATH = os.environ.get("V18357_STATE_PATH", "/var/data/v18357_capital_ladder.json")
STEP_GBP = 15.0
WINDOW = 5
MIN_WINS = 4
ROLLBACK_LOSSES = 2
POLL_SECONDS = 15
_LOCK = threading.Lock()
_RUNTIME: Dict[str, Any] = {"lastError": None, "lastEvaluation": None, "lastAction": "BASELINE"}


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


def _fresh_stock_trades(m, after_id: int) -> List[Dict[str, Any]]:
    conn = m.db_connect()
    try:
        rows = conn.execute(
            """SELECT * FROM closed_trades
               WHERE id>? AND COALESCE(qty,0)>?
                 AND ABS(COALESCE(qty,0)*COALESCE(exit_price,0))>=?
                 AND symbol NOT LIKE '%/%'
               ORDER BY id ASC""",
            (after_id, m.PHANTOM_CLOSED_TRADE_QTY_EPSILON,
             m.PHANTOM_CLOSED_TRADE_MIN_NOTIONAL_USD),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _pnl(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("pnl_gbp") or 0.0)
    except Exception:
        return 0.0


def install_v18357_capital_earnback_ladder(app, m) -> None:
    state = _load()
    if not state:
        conn = m.db_connect()
        try:
            row = conn.execute("SELECT COALESCE(MAX(id),0) AS id FROM closed_trades").fetchone()
            start_id = int(row["id"] if row else 0)
        finally:
            conn.close()
        state = {
            "version": "V18.3.57",
            "startedAt": _now(),
            "startTradeId": start_id,
            "lastProcessedTradeId": start_id,
            "rung": 0,
            "window": [],
            "pendingCapitalChangeGbp": 0.0,
            "enabled": True,
        }
        _save(state)

    def evaluate_once() -> None:
        nonlocal state
        if not state.get("enabled", True) or float(state.get("pendingCapitalChangeGbp") or 0):
            return
        for t in _fresh_stock_trades(m, int(state.get("lastProcessedTradeId") or 0)):
            pnl = _pnl(t)
            item = {
                "id": int(t.get("id") or 0),
                "symbol": str(t.get("symbol") or ""),
                "pnlGbp": round(pnl, 4),
                "win": pnl > 0,
                "timestamp": t.get("timestamp"),
            }
            window = (list(state.get("window") or []) + [item])[-WINDOW:]
            state["window"] = window
            state["lastProcessedTradeId"] = item["id"]

            wins = sum(1 for x in window if float(x["pnlGbp"]) > 0)
            losses_last3 = sum(1 for x in window[-3:] if float(x["pnlGbp"]) < 0)
            total = sum(float(x["pnlGbp"]) for x in window)
            winner_sum = sum(float(x["pnlGbp"]) for x in window if float(x["pnlGbp"]) > 0)
            worst_loss = abs(min([float(x["pnlGbp"]) for x in window] + [0.0]))
            action = "HOLD"

            if len(window) >= WINDOW and wins >= MIN_WINS and total > 0 and worst_loss <= winner_sum:
                state["pendingCapitalChangeGbp"] = STEP_GBP
                action = "EARNED +£15 RELEASE"
            elif int(state.get("rung") or 0) > 0 and (
                losses_last3 >= ROLLBACK_LOSSES or (len(window) >= WINDOW and total < 0)
            ):
                state["pendingCapitalChangeGbp"] = -STEP_GBP
                action = "ROLL BACK £15"

            _RUNTIME["lastAction"] = action
            _RUNTIME["lastEvaluation"] = {
                "trade": item,
                "winsInWindow": wins,
                "lossesLast3": losses_last3,
                "windowPnlGbp": round(total, 2),
                "action": action,
            }
            _save(state)
            if action != "HOLD":
                break

    def loop() -> None:
        while True:
            try:
                with _LOCK:
                    evaluate_once()
                _RUNTIME["lastError"] = None
            except Exception as exc:
                _RUNTIME["lastError"] = str(exc)
            time.sleep(POLL_SECONDS)

    threading.Thread(target=loop, name="v18357-capital-ladder", daemon=True).start()

    @app.get("/v18/capital-earnback-ladder")
    def capital_earnback_ladder():
        with _LOCK:
            window = list(state.get("window") or [])
            return {
                "ok": True,
                "version": "V18.3.57",
                "enabled": bool(state.get("enabled", True)),
                "stepGbp": STEP_GBP,
                "rung": int(state.get("rung") or 0),
                "earnedCapitalGbp": round(int(state.get("rung") or 0) * STEP_GBP, 2),
                "pendingCapitalChangeGbp": float(state.get("pendingCapitalChangeGbp") or 0),
                "currentWindow": window,
                "currentWindowTrades": len(window),
                "currentWindowWins": sum(1 for x in window if float(x.get("pnlGbp") or 0) > 0),
                "currentWindowPnlGbp": round(sum(float(x.get("pnlGbp") or 0) for x in window), 2),
                "qualification": "5 fresh stock closes, at least 4 green, combined P&L positive, worst loss <= winner total",
                "rollback": "2 losses in the last 3 trades OR a negative completed 5-trade window",
                "lastAction": _RUNTIME.get("lastAction"),
                "lastEvaluation": _RUNTIME.get("lastEvaluation"),
                "lastError": _RUNTIME.get("lastError"),
                "automaticMoneyMovement": False,
                "note": "Recommendation-only until a safe partial Piggy Bank release/reprotect primitive is wired. Protected money is not moved by this version.",
            }

    print(
        f"V18.3.57 CAPITAL EARNBACK LADDER | step=£{STEP_GBP:.0f} "
        f"qualify={MIN_WINS}/{WINDOW}+positive rollback={ROLLBACK_LOSSES}_losses_last3 "
        f"money_movement=False start_trade_id={state.get('startTradeId')}"
    )
