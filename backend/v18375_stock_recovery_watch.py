"""V18.3.75 Stock Loss Recovery Watch.

Replaces the V18.3.72 8-second confirmation wrapper for the
V18.2.80 stock absolute loss-guard path.

Intent:
- do not panic-sell a normal pullback at -1.5%
- enter an explicit RECOVERY WATCH instead
- give the position time to recover
- if it is genuinely bouncing, extend the watch once
- if two fresh price sources confirm a hard-floor breach, sell immediately
- if the watch expires and the loss is still confirmed, sell
- all non-loss-guard sell paths remain untouched

This module does NOT change stock entry rules, profit-taking rules,
manual sells, emergency sells, or AI-exit authority.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, Tuple

RECOVERY_TRIGGER_PCT = float(os.getenv("TRADEBOT_RECOVERY_TRIGGER_PCT", "-1.50"))
HARD_FLOOR_PCT = float(os.getenv("TRADEBOT_RECOVERY_HARD_FLOOR_PCT", "-4.00"))
WATCH_SECONDS = max(30.0, min(600.0, float(os.getenv("TRADEBOT_RECOVERY_WATCH_SECONDS", "180"))))
BOUNCE_EXTENSION_SECONDS = max(
    30.0,
    min(300.0, float(os.getenv("TRADEBOT_RECOVERY_BOUNCE_EXTENSION_SECONDS", "120"))),
)
BOUNCE_REQUIRED_PCT = max(
    0.10,
    min(3.00, float(os.getenv("TRADEBOT_RECOVERY_BOUNCE_REQUIRED_PCT", "0.60"))),
)

_lock = threading.Lock()
_watch: Dict[str, Dict[str, Any]] = {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _loss_pct(price: float, entry: float) -> float:
    if entry <= 0 or price <= 0:
        return 0.0
    return ((price - entry) / entry) * 100.0


def _extract_call_values(args, kwargs) -> Tuple[float, float, str]:
    # market_sell_qty(symbol, qty, entry=0, price=0, reason="AUTO SELL")
    entry = _num(kwargs.get("entry", args[0] if len(args) >= 1 else 0.0))
    price = _num(kwargs.get("price", args[1] if len(args) >= 2 else 0.0))
    reason = str(kwargs.get("reason", args[2] if len(args) >= 3 else ""))
    return entry, price, reason


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


def _confirmed_losses(m, symbol: str, entry: float) -> Tuple[float, float, float, float]:
    broker_price = _fresh_broker_price(m, symbol)
    quote_price = _fresh_quote_price(m, symbol)
    broker_loss = _loss_pct(broker_price, entry) if broker_price > 0 else 999.0
    quote_loss = _loss_pct(quote_price, entry) if quote_price > 0 else 999.0
    return broker_price, quote_price, broker_loss, quote_loss


def _submit_original_sell(original_market_sell_qty, symbol, qty, entry, price, reason):
    return original_market_sell_qty(
        symbol,
        qty,
        entry=entry,
        price=price,
        reason=reason,
    )


def install_v18375_stock_recovery_watch(app, m) -> None:
    original_market_sell_qty = m.market_sell_qty

    def recovery_market_sell_qty(symbol, qty, *args, **kwargs):
        entry, trigger_price, reason = _extract_call_values(args, kwargs)

        if "V18.2.80 STOCK ABSOLUTE LOSS GUARD" not in reason:
            return original_market_sell_qty(symbol, qty, *args, **kwargs)

        symbol_u = str(symbol or "").upper().strip()
        if not symbol_u or entry <= 0:
            # Preserve legacy behaviour rather than silently blocking a sell
            # if the loss-guard caller ever supplies incomplete metadata.
            return original_market_sell_qty(symbol, qty, *args, **kwargs)

        trigger_loss = _loss_pct(trigger_price, entry)
        now = time.time()

        broker_price, quote_price, broker_loss, quote_loss = _confirmed_losses(
            m, symbol_u, entry
        )
        broker_valid = broker_price > 0
        quote_valid = quote_price > 0

        # A hard-floor exit requires two independent live reads so a single
        # bad print cannot cause an immediate liquidation.
        hard_floor_confirmed = (
            broker_valid
            and quote_valid
            and broker_loss <= HARD_FLOOR_PCT
            and quote_loss <= HARD_FLOOR_PCT
        )

        if hard_floor_confirmed:
            with _lock:
                _watch.pop(symbol_u, None)
            sell_price = broker_price if broker_price > 0 else trigger_price
            print(
                f"V18.3.75 RECOVERY HARD FLOOR | {symbol_u} "
                f"broker={broker_loss:.2f}% quote={quote_loss:.2f}% "
                f"floor={HARD_FLOOR_PCT:.2f}% live_sell=True"
            )
            return _submit_original_sell(
                original_market_sell_qty,
                symbol_u,
                qty,
                entry,
                sell_price,
                f"V18.3.75 HARD FLOOR | {reason}",
            )

        with _lock:
            watch = _watch.get(symbol_u)

            # If the loss-guard caller has recovered above the trigger,
            # clear any recovery watch and keep holding.
            if trigger_loss > RECOVERY_TRIGGER_PCT:
                if watch:
                    _watch.pop(symbol_u, None)
                    print(
                        f"V18.3.75 RECOVERY CLEARED | {symbol_u} "
                        f"trigger={trigger_loss:.2f}% > watch={RECOVERY_TRIGGER_PCT:.2f}% "
                        "live_sell=False"
                    )
                return None

            if not watch:
                worst = trigger_loss
                if broker_valid:
                    worst = min(worst, broker_loss)
                if quote_valid:
                    worst = min(worst, quote_loss)
                watch = {
                    "startedAt": now,
                    "deadline": now + WATCH_SECONDS,
                    "firstLossPct": trigger_loss,
                    "worstLossPct": worst,
                    "extensionUsed": False,
                    "lastLossPct": trigger_loss,
                }
                _watch[symbol_u] = watch
                print(
                    f"V18.3.75 RECOVERY WATCH START | {symbol_u} "
                    f"loss={trigger_loss:.2f}% trigger={RECOVERY_TRIGGER_PCT:.2f}% "
                    f"watch={WATCH_SECONDS:.0f}s hard_floor={HARD_FLOOR_PCT:.2f}% "
                    "live_sell=False"
                )
                return None

            observed_losses = [trigger_loss]
            if broker_valid:
                observed_losses.append(broker_loss)
            if quote_valid:
                observed_losses.append(quote_loss)
            current_worst = min(observed_losses)
            watch["worstLossPct"] = min(
                _num(watch.get("worstLossPct"), current_worst),
                current_worst,
            )
            watch["lastLossPct"] = trigger_loss

            deadline = _num(watch.get("deadline"), now)
            remaining = deadline - now
            worst_loss = _num(watch.get("worstLossPct"), trigger_loss)

            if remaining > 0:
                print(
                    f"V18.3.75 RECOVERY WATCH HOLD | {symbol_u} "
                    f"trigger={trigger_loss:.2f}% worst={worst_loss:.2f}% "
                    f"remaining={remaining:.0f}s hard_floor={HARD_FLOOR_PCT:.2f}% "
                    "live_sell=False"
                )
                return None

            # At the end of the watch require fresh broker + quote agreement
            # before deciding whether the loss remains real.
            if not (broker_valid and quote_valid):
                watch["deadline"] = now + 30.0
                print(
                    f"V18.3.75 RECOVERY SOURCE WAIT | {symbol_u} "
                    f"broker_valid={broker_valid} quote_valid={quote_valid} "
                    "retry=30s live_sell=False"
                )
                return None

            both_still_below_trigger = (
                broker_loss <= RECOVERY_TRIGGER_PCT
                and quote_loss <= RECOVERY_TRIGGER_PCT
            )

            if not both_still_below_trigger:
                _watch.pop(symbol_u, None)
                print(
                    f"V18.3.75 RECOVERY CONFIRMED | {symbol_u} "
                    f"broker={broker_loss:.2f}% quote={quote_loss:.2f}% "
                    f"trigger={RECOVERY_TRIGGER_PCT:.2f}% hold=True live_sell=False"
                )
                return None

            current_loss = (broker_loss + quote_loss) / 2.0
            bounce_from_worst = current_loss - worst_loss

            if (
                not bool(watch.get("extensionUsed"))
                and bounce_from_worst >= BOUNCE_REQUIRED_PCT
            ):
                watch["extensionUsed"] = True
                watch["deadline"] = now + BOUNCE_EXTENSION_SECONDS
                print(
                    f"V18.3.75 RECOVERY BOUNCE | {symbol_u} "
                    f"current={current_loss:.2f}% worst={worst_loss:.2f}% "
                    f"bounce=+{bounce_from_worst:.2f}pp "
                    f"extend={BOUNCE_EXTENSION_SECONDS:.0f}s live_sell=False"
                )
                return None

            _watch.pop(symbol_u, None)
            sell_price = broker_price if broker_price > 0 else trigger_price
            print(
                f"V18.3.75 RECOVERY EXPIRED SELL | {symbol_u} "
                f"broker={broker_loss:.2f}% quote={quote_loss:.2f}% "
                f"worst={worst_loss:.2f}% bounce={bounce_from_worst:+.2f}pp "
                "live_sell=True"
            )
            return _submit_original_sell(
                original_market_sell_qty,
                symbol_u,
                qty,
                entry,
                sell_price,
                f"V18.3.75 RECOVERY EXPIRED | {reason}",
            )

    m.market_sell_qty = recovery_market_sell_qty

    print(
        "V18.3.75 STOCK RECOVERY WATCH | installed "
        f"trigger={RECOVERY_TRIGGER_PCT:.2f}% watch={WATCH_SECONDS:.0f}s "
        f"bounce=+{BOUNCE_REQUIRED_PCT:.2f}pp extend={BOUNCE_EXTENSION_SECONDS:.0f}s "
        f"hard_floor={HARD_FLOOR_PCT:.2f}% scope=V18.2.80_ONLY"
    )
