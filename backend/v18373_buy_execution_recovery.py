"""V18.3.73 Buy Execution Truth + Recovery.

Repairs the live-stock handoff between a qualified/full-buy plan and Alpaca.

Observed failure mode:
- candidate qualifies
- FULL BUY EXECUTION LOCK is logged
- no BUY event, no open order and no live position appear

This module does two things without changing entry thresholds:
1) wraps market_buy_notional with explicit SUBMIT / ACCEPTED / REJECTED logging
2) wraps money_mode_buy with a conservative one-shot recovery if the existing
   live buy path returns without creating either an open buy order or position

Recovery is intentionally strict and only runs when the existing scanner's
top pick still independently passes the current live gates.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict

_RECOVERY_MIN_CONFIDENCE = 0.70
_RECOVERY_MIN_QUALITY = 0.020
_RECOVERY_GRACE_SECONDS = 2.0
_RECOVERY_COOLDOWN_SECONDS = 60.0

_lock = threading.Lock()
_last_recovery: Dict[str, float] = {}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _positions(m):
    try:
        return list(m.get_all_positions() or [])
    except Exception:
        return []


def _has_position(m, symbol: str) -> bool:
    s = str(symbol or "").upper()
    for p in _positions(m):
        if str(p.get("symbol") or "").upper() == s and _num(p.get("qty")) > 0:
            return True
    return False


def _has_open_order(m, symbol: str) -> bool:
    try:
        return bool(m.has_open_order(symbol))
    except Exception:
        return False


def _top_existing_pick(m, scans):
    try:
        picks = list(m.pick_money_mode_stocks(scans) or [])
    except Exception:
        picks = []
    return picks[0] if picks else None


def _candidate_still_safe(m, pick) -> tuple[bool, str]:
    if not isinstance(pick, dict):
        return False, "no pick"

    symbol = str(pick.get("symbol") or "").upper().strip()
    if not symbol:
        return False, "missing symbol"

    if not bool(pick.get("ready_to_buy", True)):
        return False, "ready_to_buy false"

    confidence = _num(pick.get("confidence"))
    quality = _num(pick.get("quality_score"))

    if confidence < _RECOVERY_MIN_CONFIDENCE:
        return False, f"confidence {confidence:.2f} below recovery floor {_RECOVERY_MIN_CONFIDENCE:.2f}"
    if quality < _RECOVERY_MIN_QUALITY:
        return False, f"quality {quality:.4f} below recovery floor {_RECOVERY_MIN_QUALITY:.4f}"

    try:
        can_buy, reason = m.can_buy_symbol(symbol)
        if not can_buy:
            return False, str(reason or "can_buy_symbol blocked")
    except Exception as exc:
        return False, f"can_buy_symbol error: {exc}"

    try:
        blocked, reason = m.risk_blocked()
        if blocked:
            return False, str(reason or "risk blocked")
    except Exception as exc:
        return False, f"risk check error: {exc}"

    try:
        if int(m.allowed_new_position_count()) <= 0:
            return False, "position capacity reached"
    except Exception:
        pass

    try:
        if not bool(m.trading_client.get_clock().is_open):
            return False, "market closed"
    except Exception as exc:
        return False, f"clock error: {exc}"

    try:
        sniper_ok, reason = m.sniper_passes(pick)
        if not sniper_ok:
            return False, f"sniper blocked: {reason}"
    except Exception as exc:
        return False, f"sniper check error: {exc}"

    try:
        aplus_ok, reason = m.a_plus_gate(pick)
        if not aplus_ok:
            return False, f"A+ blocked: {reason}"
    except Exception as exc:
        return False, f"A+ check error: {exc}"

    try:
        asset = m.trading_client.get_asset(symbol)
        if not bool(getattr(asset, "tradable", False)):
            return False, "asset not tradable"
        if not bool(getattr(asset, "fractionable", False)):
            return False, "asset not fractionable for notional order"
        status = str(getattr(asset, "status", "") or "").lower()
        if status and status not in ("active", "assetstatus.active"):
            return False, f"asset status {status}"
    except Exception as exc:
        return False, f"asset preflight error: {exc}"

    return True, ""


def install_v18373_buy_execution_recovery(app, m) -> None:
    original_market_buy_notional = m.market_buy_notional
    original_money_mode_buy = m.money_mode_buy

    def traced_market_buy_notional(symbol: str, notional_amount: float, reason="AUTO BUY", **metadata):
        symbol_u = str(symbol or "").upper().strip()
        amount = round(_num(notional_amount), 2)
        if metadata:
            print(
                f"V18.3.77 BUY HANDOFF METADATA | symbol={symbol_u} "
                f"ignored={','.join(sorted(metadata.keys()))}"
            )
        print(
            f"V18.3.73 BUY SUBMIT | symbol={symbol_u} notional=${amount:.2f} "
            f"reason={reason}"
        )
        try:
            result = original_market_buy_notional(symbol_u, amount, reason=reason)
            order_id = ""
            status = ""
            try:
                order_id = str(getattr(result, "id", "") or "")
                status = str(getattr(result, "status", "") or "")
            except Exception:
                pass
            print(
                f"V18.3.73 BUY ACCEPTED | symbol={symbol_u} notional=${amount:.2f} "
                f"order_id={order_id or '-'} status={status or 'submitted'}"
            )
            return result
        except Exception as exc:
            print(
                f"V18.3.73 BUY REJECTED | symbol={symbol_u} notional=${amount:.2f} "
                f"error={type(exc).__name__}: {exc}"
            )
            raise

    def reliable_money_mode_buy(scans, manual=False):
        pick = _top_existing_pick(m, scans) if not manual else None
        pick_symbol = str((pick or {}).get("symbol") or "").upper().strip()

        before_position = _has_position(m, pick_symbol) if pick_symbol else False
        before_order = _has_open_order(m, pick_symbol) if pick_symbol else False

        result = original_money_mode_buy(scans, manual=manual)

        # Manual flow remains exactly as implemented by the existing bot.
        if manual or not pick_symbol:
            return result

        # Existing path succeeded: nothing else to do.
        if before_position or before_order:
            return result

        time.sleep(_RECOVERY_GRACE_SECONDS)

        if _has_position(m, pick_symbol):
            print(f"V18.3.73 BUY CONFIRMED | symbol={pick_symbol} source=existing-path position=True")
            return result

        if _has_open_order(m, pick_symbol):
            print(f"V18.3.73 BUY CONFIRMED | symbol={pick_symbol} source=existing-path open_order=True")
            return result

        safe, why = _candidate_still_safe(m, pick)
        if not safe:
            print(
                f"V18.3.73 BUY NO-ORDER | symbol={pick_symbol} "
                f"existing_result={result!r} recovery=False reason={why}"
            )
            return result

        with _lock:
            now = time.time()
            last = _last_recovery.get(pick_symbol, 0.0)
            if now - last < _RECOVERY_COOLDOWN_SECONDS:
                print(
                    f"V18.3.73 BUY NO-ORDER | symbol={pick_symbol} "
                    f"recovery=False reason=recovery cooldown"
                )
                return result
            _last_recovery[pick_symbol] = now

        try:
            notional = _num(m.confidence_notional(pick))
        except Exception as exc:
            print(
                f"V18.3.73 BUY RECOVERY BLOCKED | symbol={pick_symbol} "
                f"reason=notional error: {exc}"
            )
            return result

        try:
            min_notional = _num(getattr(m, "MIN_ORDER_NOTIONAL", 1.0), 1.0)
            if notional < min_notional:
                print(
                    f"V18.3.73 BUY RECOVERY BLOCKED | symbol={pick_symbol} "
                    f"notional=${notional:.2f} minimum=${min_notional:.2f}"
                )
                return result
        except Exception:
            pass

        print(
            f"V18.3.73 BUY RECOVERY | symbol={pick_symbol} "
            f"notional=${notional:.2f} existing_result={result!r}"
        )

        try:
            m.market_buy_notional(
                pick_symbol,
                notional,
                reason="AUTO V16 EXECUTION RECOVERY BUY",
            )
        except Exception:
            return result

        # Confirm broker evidence. Never fire a second recovery order.
        for _ in range(10):
            if _has_position(m, pick_symbol):
                print(
                    f"V18.3.73 BUY RECOVERY CONFIRMED | symbol={pick_symbol} "
                    "position=True"
                )
                return result
            if _has_open_order(m, pick_symbol):
                print(
                    f"V18.3.73 BUY RECOVERY CONFIRMED | symbol={pick_symbol} "
                    "open_order=True"
                )
                return result
            time.sleep(0.5)

        print(
            f"V18.3.73 BUY RECOVERY UNRESOLVED | symbol={pick_symbol} "
            "no_position=True no_open_order=True"
        )
        return result

    m.market_buy_notional = traced_market_buy_notional
    m.money_mode_buy = reliable_money_mode_buy

    print(
        "V18.3.73 BUY EXECUTION RECOVERY | installed "
        f"grace={_RECOVERY_GRACE_SECONDS:.0f}s min_conf={_RECOVERY_MIN_CONFIDENCE:.2f} "
        f"min_quality={_RECOVERY_MIN_QUALITY:.4f} cooldown={_RECOVERY_COOLDOWN_SECONDS:.0f}s "
        "entry_gates=UNCHANGED"
    )
