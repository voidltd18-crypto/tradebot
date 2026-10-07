"""V18.3.72 Stock Absolute Loss Guard Confirmation.

Protects live stock positions from being sold on one transient/bad price print.
Only the V18.2.80 STOCK ABSOLUTE LOSS GUARD path is wrapped.
All other buy/sell paths are untouched.

Behaviour:
- first loss-guard sell request is held as PENDING
- a second qualifying request must arrive at least CONFIRM_SECONDS later
- a fresh broker position snapshot and fresh quote must still corroborate the loss
- if price recovers above the guard threshold, the pending confirmation is cleared
- confirmation expires so stale signals cannot trigger a later sell
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict

CONFIRM_SECONDS = max(3.0, min(30.0, float(os.getenv("TRADEBOT_LOSS_GUARD_CONFIRM_SECONDS", "8"))))
CONFIRM_EXPIRY_SECONDS = max(CONFIRM_SECONDS + 5.0, min(120.0, float(os.getenv("TRADEBOT_LOSS_GUARD_CONFIRM_EXPIRY_SECONDS", "45"))))
LOSS_LIMIT_PCT = float(os.getenv("TRADEBOT_LOSS_GUARD_LIMIT_PCT", "-1.50"))

_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _loss_pct(price: float, entry: float) -> float:
    if entry <= 0:
        return 0.0
    return ((price - entry) / entry) * 100.0


def _fresh_broker_price(m, symbol: str) -> float:
    try:
        for p in m.get_all_positions():
            if str(p.get("symbol") or "").upper() == symbol:
                return _num(p.get("price") or p.get("current_price"))
    except Exception:
        pass
    return 0.0


def _fresh_quote_price(m, symbol: str) -> float:
    try:
        q = m.get_quote(symbol)
        return _num(q.get("mid") or q.get("price"))
    except Exception:
        return 0.0


def install_v18372_loss_guard_confirmation(app, m) -> None:
    original_market_sell_qty = m.market_sell_qty

    def guarded_market_sell_qty(symbol, qty, *args, **kwargs):
        reason = str(kwargs.get("reason") or "")
        if "V18.2.80 STOCK ABSOLUTE LOSS GUARD" not in reason:
            return original_market_sell_qty(symbol, qty, *args, **kwargs)

        symbol_u = str(symbol or "").upper().strip()
        entry = _num(kwargs.get("entry"))
        trigger_price = _num(kwargs.get("price"))
        trigger_loss = _loss_pct(trigger_price, entry)
        now = time.time()

        with _lock:
            pending = _pending.get(symbol_u)

            # If the guard caller itself is no longer below the configured
            # threshold, discard any stale pending confirmation.
            if trigger_loss > LOSS_LIMIT_PCT:
                if pending:
                    _pending.pop(symbol_u, None)
                    print(
                        f"V18.3.72 LOSS GUARD RECOVERED | {symbol_u} "
                        f"trigger={trigger_loss:.2f}% > limit={LOSS_LIMIT_PCT:.2f}% pending_cleared=True"
                    )
                return None

            if not pending or (now - _num(pending.get("at"))) > CONFIRM_EXPIRY_SECONDS:
                _pending[symbol_u] = {
                    "at": now,
                    "entry": entry,
                    "firstPrice": trigger_price,
                    "firstLossPct": trigger_loss,
                }
                print(
                    f"V18.3.72 LOSS GUARD PENDING | {symbol_u} "
                    f"loss={trigger_loss:.2f}% limit={LOSS_LIMIT_PCT:.2f}% "
                    f"confirm_after={CONFIRM_SECONDS:.0f}s live_sell=False"
                )
                return None

            age = now - _num(pending.get("at"))
            if age < CONFIRM_SECONDS:
                print(
                    f"V18.3.72 LOSS GUARD WAIT | {symbol_u} "
                    f"loss={trigger_loss:.2f}% age={age:.1f}s/{CONFIRM_SECONDS:.0f}s live_sell=False"
                )
                return None

            broker_price = _fresh_broker_price(m, symbol_u)
            quote_price = _fresh_quote_price(m, symbol_u)
            broker_loss = _loss_pct(broker_price, entry) if broker_price > 0 else 999.0
            quote_loss = _loss_pct(quote_price, entry) if quote_price > 0 else 999.0

            # Require both independent fresh reads to corroborate the loss.
            # If either source recovers, treat the original trigger as suspect.
            broker_confirms = broker_price > 0 and broker_loss <= LOSS_LIMIT_PCT
            quote_confirms = quote_price > 0 and quote_loss <= LOSS_LIMIT_PCT

            if not (broker_confirms and quote_confirms):
                _pending.pop(symbol_u, None)
                print(
                    f"V18.3.72 LOSS GUARD CANCELLED | {symbol_u} "
                    f"trigger={trigger_loss:.2f}% broker={broker_loss:.2f}% quote={quote_loss:.2f}% "
                    f"limit={LOSS_LIMIT_PCT:.2f}% live_sell=False"
                )
                return None

            _pending.pop(symbol_u, None)
            print(
                f"V18.3.72 LOSS GUARD CONFIRMED | {symbol_u} "
                f"first={_num(pending.get('firstLossPct')):.2f}% trigger={trigger_loss:.2f}% "
                f"broker={broker_loss:.2f}% quote={quote_loss:.2f}% "
                f"age={age:.1f}s live_sell=True"
            )

        return original_market_sell_qty(symbol, qty, *args, **kwargs)

    m.market_sell_qty = guarded_market_sell_qty

    print(
        "V18.3.72 LOSS GUARD CONFIRMATION | installed "
        f"limit={LOSS_LIMIT_PCT:.2f}% confirm={CONFIRM_SECONDS:.0f}s expiry={CONFIRM_EXPIRY_SECONDS:.0f}s "
        "scope=V18.2.80_ONLY"
    )
